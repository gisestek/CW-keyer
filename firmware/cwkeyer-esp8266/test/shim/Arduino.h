// Testishim: korvaa ESP8266 Arduino-ytimen PC-testeissä.
#pragma once
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <functional>
#define IRAM_ATTR
#define HIGH 1
#define LOW 0
#define OUTPUT 1
static const uint8_t D1 = 5;
static const uint8_t D4 = 2;
extern uint32_t GPOS_reg, GPOC_reg, gpio_out;
struct GpioSet { GpioSet& operator=(uint32_t m) { gpio_out |= m; return *this; } };
struct GpioClr { GpioClr& operator=(uint32_t m) { gpio_out &= ~m; return *this; } };
extern GpioSet GPOS;
extern GpioClr GPOC;
inline void digitalWrite(uint8_t pin, int v) { if (v) gpio_out |= (1u << pin); else gpio_out &= ~(1u << pin); }
inline void pinMode(uint8_t, int) {}
#define TIM_DIV16 0
#define TIM_EDGE 0
#define TIM_LOOP 0
extern void (*timer1_cb)();
inline void timer1_isr_init() {}
inline void timer1_attachInterrupt(void (*cb)()) { timer1_cb = cb; }
inline void timer1_enable(int, int, int) {}
inline void timer1_write(uint32_t) {}
void delay(unsigned long ms);
