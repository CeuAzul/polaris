/*
 * ============================================================
 *  Firmware Bancada - Leitor de 2x HX711 + RPM
 *  ------------------------------------------------------------
 *  - Empuxo: HX711 em DT=D3, SCK=D4
 *  - Torque: HX711 em DT=D5, SCK=D6
 *  - RPM:    fio AMARELO do ESC ligado em D7 (PCINT - PCMSK2)
 *
 *  IMPORTANTE: o D7 NAO tem interrupcao externa (INT0/INT1).
 *  Usamos Pin Change Interrupt (PCINT) que funciona em qualquer
 *  pino digital. Em performance e identico a INT0/INT1.
 *
 *  Saida serial (115200 baud), uma linha por amostra:
 *    raw_e,raw_t,pulsos,dt_us\n
 *
 *    raw_e  : leitura bruta da celula de empuxo (long)
 *    raw_t  : leitura bruta da celula de torque (long)
 *    pulsos : pulsos do ESC desde a linha anterior (uint)
 *    dt_us  : microssegundos desde a linha anterior (ulong)
 *
 *  RPM eletrico = pulsos / (dt_us * 1e-6) * 60.0   [Python calcula]
 *  RPM mecanico = RPM eletrico / pares_de_polos
 *
 *  Comandos do PC (via serial):
 *    P/p -> pausa o envio
 *    R/r -> retoma o envio
 *    I/i -> identificacao (responde "ID:THRUST_RIG_V2")
 *
 *  Autor: equipe Ceu Azul - Aerodesign
 *  Versao: 2.0 (RPM via PCINT no D7)
 * ============================================================
 */

#include "HX711.h"

#define DT_EMPUXO   3
#define SCK_EMPUXO  4
#define DT_TORQUE   5
#define SCK_TORQUE  6
#define PIN_RPM     7   // PCINT23 no Arduino Nano (porta PCMSK2)

HX711 celulaEmpuxo;
HX711 celulaTorque;

// Intervalo minimo entre pulsos validos (us).
// Para 15000 RPM mecanicos x 7 pares de polos = 105000 rpm eletrico
// = 1750 Hz => periodo = 571 us. Usamos 400 us como margem de segurança.
#define DEBOUNCE_US  400UL

volatile unsigned long pulsoCount = 0;
volatile uint8_t portD_anterior = 0;
volatile unsigned long ultimoPulso_us = 0;
unsigned long ultimoEnvio_us = 0;

bool enviando = true;

// =============================================================
// Pin Change Interrupt para a porta D (PCINT16..23 = D0..D7)
// Detecta apenas borda de SUBIDA no D7 com debounce.
// =============================================================
ISR(PCINT2_vect) {
  uint8_t agora = PIND;
  uint8_t mudou = agora ^ portD_anterior;
  portD_anterior = agora;
  // bit 7 = D7. Se mudou e esta em 1 -> borda de subida
  if ((mudou & (1 << PIND7)) && (agora & (1 << PIND7))) {
    unsigned long agora_us = micros();
    // ignora pulsos que chegam rapido demais (ruido/bouncing do ESC)
    if ((agora_us - ultimoPulso_us) >= DEBOUNCE_US) {
      pulsoCount++;
      ultimoPulso_us = agora_us;
    }
  }
}

void setup() {
  Serial.begin(115200);
  while (!Serial) { ; }

  celulaEmpuxo.begin(DT_EMPUXO, SCK_EMPUXO);
  celulaTorque.begin(DT_TORQUE, SCK_TORQUE);

  pinMode(PIN_RPM, INPUT_PULLUP);

  // Habilita PCINT na porta D, mascara apenas o D7 (PCINT23)
  noInterrupts();
  portD_anterior = PIND;
  PCICR  |= (1 << PCIE2);            // habilita grupo PCI2 (porta D)
  PCMSK2 |= (1 << PCINT23);          // habilita interrupcao no D7
  interrupts();

  delay(200);
  ultimoEnvio_us = micros();
  Serial.println(F("ID:THRUST_RIG_V2"));
}

void loop() {
  // ---- Comandos do PC ----
  if (Serial.available() > 0) {
    char c = Serial.read();
    switch (c) {
      case 'P': case 'p':
        enviando = false;
        Serial.println(F("PAUSED"));
        break;
      case 'R': case 'r':
        enviando = true;
        // ressincroniza tempo e zera pulsos para nao computar dt gigante
        ultimoEnvio_us = micros();
        noInterrupts();
        pulsoCount = 0;
        interrupts();
        Serial.println(F("RESUMED"));
        break;
      case 'I': case 'i':
        Serial.println(F("ID:THRUST_RIG_V2"));
        break;
      default:
        break;
    }
  }

  if (!enviando) return;

  // ---- Le as duas celulas ----
  if (celulaEmpuxo.is_ready() && celulaTorque.is_ready()) {
    long rawE = celulaEmpuxo.read();
    long rawT = celulaTorque.read();

    // Captura pulsos atomicamente
    noInterrupts();
    unsigned long pulsos = pulsoCount;
    pulsoCount = 0;
    interrupts();

    unsigned long agora = micros();
    unsigned long dt_us = agora - ultimoEnvio_us;
    ultimoEnvio_us = agora;

    Serial.print(rawE);
    Serial.print(',');
    Serial.print(rawT);
    Serial.print(',');
    Serial.print(pulsos);
    Serial.print(',');
    Serial.println(dt_us);
  }
}
