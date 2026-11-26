#ifndef COKVM_PROTOCOL_H
#define COKVM_PROTOCOL_H

#include <stdint.h>
#include <zephyr/toolchain.h>

#define COKVM_PROTO_MAGIC_K         0x4b
#define COKVM_PROTO_MAGIC_M         0x4d
#define COKVM_PROTO_VERSION_0       0x00

#define COKVM_MSG_TYPE_KBD_DATA     0x01
#define COKVM_MSG_TYPE_MOUSE_DATA   0x02
#define COKVM_MSG_TYPE_LED_STATUS   0x03

#define COKVM_MSG_VSS_PAYLOAD_LEN   22
#define COKVM_MSG_VSS_LEN           22
#define COKVM_MSG_KBD_REPORT_ID     0x01
#define COKVM_MSG_MOUSE_REPORT_ID   0x02

// only care about num lock and caps lock led
#define COKVM_KBD_LED_MASK          (HID_KBD_LED_NUM_LOCK | HID_KBD_LED_CAPS_LOCK)

#define COKVM_KBD_DELAY_UNIT_MS     10

typedef struct {
    uint8_t modifiers;
    uint8_t delay;       /* delay units (10ms each), 0 = immediate */
    uint8_t keycodes[6];
} __packed cokvm_kbd_data_t;

typedef struct {
    uint8_t buttons;
    int16_t x;
    int16_t y;
    int8_t  wheel;
} __packed cokvm_mouse_data_t;

/* to/from USB HID report payload */
typedef struct {
    uint8_t report_id;
    union {
        cokvm_kbd_data_t   kbd;
        cokvm_mouse_data_t mouse;
        uint8_t led_status;
    } data;
} __packed cokvm_usb_payload_t;

/* to/from Bluetooth BLE VSS payload */
typedef struct {
    uint8_t  magic_k;
    uint8_t  magic_m;
    uint8_t  version;
    uint8_t  type;
    union {
        cokvm_kbd_data_t   kbd;
        cokvm_mouse_data_t mouse;
        uint8_t led_status;
    } data;
    uint8_t  reserved[10];
} __packed cokvm_vss_payload_t;

#endif
