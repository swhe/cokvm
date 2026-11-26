#include <stdint.h>
#include <string.h>
#include <stdbool.h>
#include <zephyr/kernel.h>
#include <zephyr/drivers/hwinfo.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/controller.h>
#include <zephyr/bluetooth/hci.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/usb/class/hid.h>
#include <zephyr/settings/settings.h>
#include <zephyr/logging/log.h>
#include "cokvm_protocol.h"
#include "cokvm_bt.h"
#include "cokvm_usb.h"
#include "cokvm_queue.h"
#include "cokvm_ui.h"


LOG_MODULE_REGISTER(cokvm_bt, LOG_LEVEL_INF);

#define PAIRING_WINDOW_MS 60000

static struct bt_conn *current_conn = NULL;
static struct k_timer pairing_window_timer;

static bt_addr_le_t last_bonded_peer;

#define BT_UUID_COKVM_VSS_SERVICE_VAL 0xff00
#define BT_UUID_COKVM_VSS_DATA_VAL    0xff1d
#define BT_UUID_COKVM_VSS_INFO_VAL    0xff2c

#define BT_UUID_COKVM_VSS_SERVICE    BT_UUID_DECLARE_16(BT_UUID_COKVM_VSS_SERVICE_VAL)
#define BT_UUID_COKVM_VSS_DATA       BT_UUID_DECLARE_16(BT_UUID_COKVM_VSS_DATA_VAL)
#define BT_UUID_COKVM_VSS_INFO       BT_UUID_DECLARE_16(BT_UUID_COKVM_VSS_INFO_VAL)

static struct bt_le_adv_param adv_param = {
    .options = BT_LE_ADV_OPT_CONN | BT_LE_ADV_OPT_SCANNABLE,
    .interval_min = BT_GAP_ADV_FAST_INT_MIN_2,
    .interval_max = BT_GAP_ADV_FAST_INT_MAX_2,
};

static const struct bt_data ad[] = {
    BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
    BT_DATA_BYTES(BT_DATA_UUID16_ALL,
                  BT_UUID_16_ENCODE(BT_UUID_COKVM_VSS_SERVICE_VAL)),
};

static const struct bt_data sd[] = {
    BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME, sizeof(CONFIG_BT_DEVICE_NAME) - 1),
    BT_DATA_BYTES(BT_DATA_GAP_APPEARANCE, 0x00, 0x00),
    BT_DATA_BYTES(BT_DATA_UUID16_ALL,
                  BT_UUID_16_ENCODE(BT_UUID_DIS_VAL), BT_UUID_16_ENCODE(BT_UUID_BAS_VAL)),
};

static ssize_t write_vss_data(struct bt_conn *conn, const struct bt_gatt_attr *attr,
                              const void *buf, uint16_t len, uint16_t offset, uint8_t flags);
static ssize_t read_vss_info(struct bt_conn *conn, const struct bt_gatt_attr *attr,
                             void *buf, uint16_t len, uint16_t offset);

BT_GATT_SERVICE_DEFINE(
    vss_service,
    BT_GATT_PRIMARY_SERVICE(BT_UUID_COKVM_VSS_SERVICE),
    BT_GATT_CHARACTERISTIC(BT_UUID_COKVM_VSS_DATA,
        BT_GATT_CHRC_WRITE_WITHOUT_RESP,
        BT_GATT_PERM_WRITE_AUTHEN,
        NULL, write_vss_data, NULL),
    BT_GATT_CHARACTERISTIC(BT_UUID_COKVM_VSS_INFO,
        BT_GATT_CHRC_READ,
        BT_GATT_PERM_READ_AUTHEN,
        read_vss_info, NULL, NULL),
);

static ssize_t read_vss_info(struct bt_conn *conn, const struct bt_gatt_attr *attr,
                             void *buf, uint16_t len, uint16_t offset)
{
    ARG_UNUSED(conn);
    ARG_UNUSED(attr);

    static const char info_str[] = "OK";
    return bt_gatt_attr_read(conn, attr, buf, len, offset,
                             info_str, sizeof(info_str) - 1);
}

static ssize_t write_vss_data(struct bt_conn *conn, const struct bt_gatt_attr *attr,
                              const void *buf, uint16_t len, uint16_t offset, uint8_t flags)
{
    ARG_UNUSED(conn);
    ARG_UNUSED(attr);
    ARG_UNUSED(offset);
    ARG_UNUSED(flags);

    if (len < COKVM_MSG_VSS_LEN) {
        return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
    }

    const cokvm_vss_payload_t *payload = (const cokvm_vss_payload_t *) buf;

    if (payload->magic_k != COKVM_PROTO_MAGIC_K ||
        payload->magic_m != COKVM_PROTO_MAGIC_M ||
        payload->version != COKVM_PROTO_VERSION_0 ||
        (payload->type < COKVM_MSG_TYPE_KBD_DATA || payload->type > COKVM_MSG_TYPE_LED_STATUS)) {
        return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
    }

    if (payload->type == COKVM_MSG_TYPE_KBD_DATA || payload->type == COKVM_MSG_TYPE_MOUSE_DATA) {
        if (ck_usb_tx_submit_from_vss_payload(payload)) {
            return BT_GATT_ERR(BT_ATT_ERR_INSUFFICIENT_RESOURCES);
        }
    } else {
        uint8_t target_led_status = payload->data.led_status & COKVM_KBD_LED_MASK;
        LOG_INF("received led: 0x%02x, current: 0x%02x, syncstate: %d", target_led_status, kbd_led, kbd_led_syncstate);

        k_spinlock_key_t key = k_spin_lock(&led_sync_lock);

        if (kbd_led_syncstate == SYNCED) {
            if (target_led_status != kbd_led) {
                uint8_t diff = kbd_led ^ target_led_status;
                kbd_led = target_led_status;
                kbd_led_syncstate = SYNCING;
                sync_retry_count = 0;
                k_spin_unlock(&led_sync_lock, key);
                int ret = ck_usb_tx_submit_led(diff);
                if (ret) {
                    LOG_ERR("ck_usb_tx_submit_led failed with ret %d", ret);
                }
            } else {
                k_spin_unlock(&led_sync_lock, key);
            }
        } else if (kbd_led_syncstate == SYNCING) {
            // Check whether the state has changed
            if (target_led_status == kbd_led) {
                // State matches; ignore
                k_spin_unlock(&led_sync_lock, key);
                LOG_INF("LED status unchanged during sync: 0x%02x", target_led_status);
            } else {
                // State changed; update and restart sync
                uint8_t prev_led = kbd_led;
                kbd_led = target_led_status;
                sync_retry_count = 0;  // Reset retry counter

                k_spin_unlock(&led_sync_lock, key);

                // Send diff to restart sync
                uint8_t diff = prev_led ^ target_led_status;
                LOG_INF("New LED status during sync: 0x%02x -> 0x%02x (diff: 0x%02x)",
                         prev_led, target_led_status, diff);
                int ret = ck_usb_tx_submit_led(diff);
                if (ret) {
                    LOG_ERR("ck_usb_tx_submit_led failed with ret %d", ret);
                }
            }
        } else {
            k_spin_unlock(&led_sync_lock, key);
            LOG_INF("wait for host to set led status");
        }
    }
    return len;
}

static void pairing_window_timeout_cb(struct k_timer *timer)
{
    ARG_UNUSED(timer);

    LOG_INF("pairing window timeout, closing pairing gate");

    bt_set_bondable(false);
    if (ck_ui_get_status() == COKVM_UI_STATUS_PAIRING) {
        ck_ui_set_status(COKVM_UI_STATUS_NORMAL);
    }
}

static void connected(struct bt_conn *conn, uint8_t err)
{
    if (err) {
        LOG_ERR("connection failed (err 0x%02x)", err);
        return;
    }
    LOG_INF("connected successfully");

    current_conn = bt_conn_ref(conn);

    bt_addr_le_copy(&last_bonded_peer, bt_conn_get_dst(conn));
    char addr_str[BT_ADDR_LE_STR_LEN];
    bt_addr_le_to_str(&last_bonded_peer, addr_str, sizeof(addr_str));
    LOG_INF("saved bonded peer address: %s", addr_str);

    int sec_err = bt_conn_set_security(conn, BT_SECURITY_L2);
    if (sec_err) {
        LOG_ERR("failed to set security: %d", sec_err);
    }
}

static void security_changed(struct bt_conn *conn, bt_security_t level, enum bt_security_err err)
{
    ARG_UNUSED(conn);

    if (err != BT_SECURITY_ERR_SUCCESS) {
        LOG_WRN("security changed failed: err %d level %d", err, level);
        ck_ui_set_status(COKVM_UI_STATUS_CONNECTED);
        return;
    }

    if (level >= BT_SECURITY_L2) {
        LOG_INF("security changed: encrypted connection established (level %d)", level);
    } else {
        LOG_WRN("security changed: level %d below expected", level);
    }
    ck_ui_set_status(COKVM_UI_STATUS_CONNECTED);
}

static void disconnected(struct bt_conn *conn, uint8_t reason)
{
    ARG_UNUSED(conn);
    ARG_UNUSED(reason);

    LOG_INF("disconnected");

    if (current_conn) {
        bt_conn_unref(current_conn);
        current_conn = NULL;
    }

    ck_ui_set_status(COKVM_UI_STATUS_NORMAL);
}

static void recycled(void)
{
    int err;

    err = bt_le_adv_start(&adv_param, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
    if (err) {
        ck_ui_set_status(COKVM_UI_STATUS_ERROR);
        LOG_ERR("recycled: start advertising failed (err %d)", err);
    } else {
        LOG_INF("recycled: advertising started with identity address");
    }
}

BT_CONN_CB_DEFINE(conn_callbacks) = {
    .connected = connected,
    .disconnected = disconnected,
    .recycled = recycled,
    .security_changed = security_changed,
};

static void auth_pairing_complete(struct bt_conn *conn, bool bonded)
{
    ARG_UNUSED(conn);

    LOG_INF("pairing complete, bonded: %s", bonded ? "true" : "false");

    bt_set_bondable(false);

    if (bonded) {
        settings_save();

        LOG_INF("bond saved, entering CONNECTED state");
        ck_ui_set_status(COKVM_UI_STATUS_CONNECTED);
    } else {
        ck_ui_set_status(COKVM_UI_STATUS_NORMAL);
    }

    k_timer_stop(&pairing_window_timer);
}

static void auth_pairing_failed(struct bt_conn *conn, enum bt_security_err reason)
{
    LOG_ERR("pairing failed, reason: %d", reason);

    if (ck_ui_get_status() == COKVM_UI_STATUS_PAIRING) {
        bt_set_bondable(false);
        ck_ui_set_status(COKVM_UI_STATUS_NORMAL);
        k_timer_stop(&pairing_window_timer);
    }
}

static struct bt_conn_auth_info_cb auth_info_callbacks = {
    .pairing_complete = auth_pairing_complete,
    .pairing_failed = auth_pairing_failed,
};

struct bt_bond_check_ctx {
    const bt_addr_le_t *addr;
    bool bonded;
};

static void bond_check(const struct bt_bond_info *info, void *user_data)
{
    struct bt_bond_check_ctx *ctx = (struct bt_bond_check_ctx *)user_data;
    if (bt_addr_le_cmp(&info->addr, ctx->addr) == 0) {
        ctx->bonded = true;
    }
}

static bool is_bonded_device(const struct bt_conn *conn)
{
    struct bt_bond_check_ctx ctx = {
        .addr = bt_conn_get_dst(conn),
        .bonded = false,
    };

    bt_foreach_bond(BT_ID_DEFAULT, bond_check, &ctx);

    return ctx.bonded;
}

#if IS_ENABLED(CONFIG_COKVM_PASSKEY_PAIRING)
static enum bt_security_err pairing_accept(struct bt_conn *conn, const struct bt_conn_pairing_feat * const feat)
{
    ARG_UNUSED(feat);

    if (ck_ui_get_status() == COKVM_UI_STATUS_PAIRING) {
        LOG_INF("accepting pairing attempt within pairing window");
        return 0;
    }

    if (is_bonded_device(conn)) {
        LOG_INF("accepting reconnection from bonded device");
        return 0;
    }

    LOG_WRN("rejecting pairing attempt outside pairing window");
    return BT_SECURITY_ERR_PAIR_NOT_ALLOWED;
}

static void passkey_display(struct bt_conn *conn, unsigned int passkey)
{
    ARG_UNUSED(conn);

    LOG_INF("pairing passkey: %06u", passkey);
}

static void auth_cancel(struct bt_conn *conn)
{
    ARG_UNUSED(conn);
}

static struct bt_conn_auth_cb auth_cb_display = {
    .pairing_accept = pairing_accept,
    .passkey_display = passkey_display,
    .cancel = auth_cancel,
};
#endif

int ck_bt_init(void)
{
    int err;
    uint8_t mac_addr[6];

    hwinfo_get_device_id(mac_addr, sizeof(mac_addr));
    mac_addr[5] = mac_addr[5] | 0xc0;
    bt_ctlr_set_public_addr(mac_addr);

    err = bt_enable(NULL);
    if (err) {
        LOG_ERR("bluetooth init failed (err %d)", err);
        return err;
    }
    settings_load();

#if IS_ENABLED(CONFIG_COKVM_PASSKEY_PAIRING)
    err = bt_conn_auth_cb_register(&auth_cb_display);
    if (err) {
        LOG_ERR("failed to register auth callbacks (err %d)", err);
    }
#endif

    err = bt_conn_auth_info_cb_register(&auth_info_callbacks);
    if (err) {
        LOG_ERR("failed to register auth info callbacks (err %d)", err);
        return err;
    }

    k_timer_init(&pairing_window_timer, pairing_window_timeout_cb, NULL);

    err = bt_le_adv_start(&adv_param, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
    if (err) {
        LOG_ERR("start advertising failed (err %d)", err);
        return err;
    } else {
        LOG_INF("advertising started");
    }

    return 0;
}

void ck_bt_start_pairing_window(void)
{
    LOG_INF("opening pairing window");

    bt_set_bondable(true);
    ck_ui_set_status(COKVM_UI_STATUS_PAIRING);
    k_timer_start(&pairing_window_timer, K_MSEC(PAIRING_WINDOW_MS), K_FOREVER);
}

bool ck_bt_is_connected(void)
{
    return (current_conn != NULL);
}

#if IS_ENABLED(CONFIG_COKVM_TESTSUITE)
int ck_bt_inject_test_data(const cokvm_vss_payload_t *payload)
{
    if (!payload) {
        return -EINVAL;
    }

    if (payload->type == COKVM_MSG_TYPE_KBD_DATA || payload->type == COKVM_MSG_TYPE_MOUSE_DATA) {
        return ck_usb_tx_submit_from_vss_payload(payload);
    }

    return -EINVAL;
}
#endif
