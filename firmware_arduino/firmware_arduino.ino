/*
 * ============================================================
 *  Firmware POLARIS - Bancada de Empuxo Estatico/Dinamico
 *  Versao 3.0 (Pitot via MS4525DO em I2C)
 *  ------------------------------------------------------------
 *  Empuxo : HX711 em DT=D3, SCK=D4
 *  Torque : HX711 em DT=D5, SCK=D6
 *  RPM    : fio AMARELO do ESC ligado em D7 (PCINT - PCMSK2)
 *  Pitot  : MS4525DO via I2C (SDA=A4, SCL=A5)
 *
 *  Compatibilidade: a presenca do Pitot e DETECTADA em runtime.
 *  Se o sensor nao responder, raw_pitot=0 e status_pitot=4 sao
 *  enviados como sentinela. O app Python sabe interpretar.
 *
 *  IMPORTANTE: o D7 NAO tem interrupcao externa (INT0/INT1).
 *  Usamos Pin Change Interrupt (PCINT) que funciona em qualquer
 *  pino digital. Em performance e identico a INT0/INT1.
 *
 *  Saida serial (115200 baud), uma linha por amostra:
 *    raw_e,raw_t,pulsos,dt_us,raw_pitot,status_pitot\n
 *
 *    raw_e        : leitura bruta da celula de empuxo (long)
 *    raw_t        : leitura bruta da celula de torque (long)
 *    pulsos       : pulsos do ESC desde a linha anterior (uint)
 *    dt_us        : microssegundos desde a linha anterior (ulong)
 *    raw_pitot    : contagem bruta do MS4525DO (0..16383)
 *    status_pitot : 0=ok, 1=reservado, 2=stale, 3=fault, 4=ausente
 *
 *  Conversao Pa <-> raw fica no Python (configuravel por sensor).
 *
 *  Comandos do PC (via serial):
 *    P/p -> pausa o envio
 *    R/r -> retoma o envio
 *    I/i -> identificacao (responde "ID:THRUST_RIG_V3")
 *
 *  Autor: equipe Ceu Azul - Aerodesign
 * ============================================================
 */

#include "HX711.h"
#include <Wire.h>

#define DT_EMPUXO   3
#define SCK_EMPUXO  4
#define DT_TORQUE   5
#define SCK_TORQUE  6
#define PIN_RPM     7   // PCINT23 no Arduino Nano (porta PCMSK2)

// MS4525DO endereco I2C padrao
#define MS4525_ADDR 0x28

// Status do Pitot
#define PITOT_OK       0
#define PITOT_RESERVED 1
#define PITOT_STALE    2
#define PITOT_FAULT    3
#define PITOT_AUSENTE  4   // sensor nao responde (NACK)

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

// Cache do Pitot (para nao bloquear se a I2C falhar). Atualizado pelo
// loop a cada iteracao se o sensor estiver presente.
uint16_t pitotRawCache = 0;
uint8_t  pitotStatusCache = PITOT_AUSENTE;

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

// =============================================================
// Le um frame de 4 bytes do MS4525DO.
// Formato:
//   B0: [status(2)] [pressao MSB(6)]
//   B1: [pressao LSB(8)]
//   B2: [temperatura MSB(8)]
//   B3: [temperatura LSB(3)] [reservado(5)]
//
// Ignoramos a temperatura aqui (nao precisamos para conversao Pa->V).
// Retorna true se a comunicacao foi bem-sucedida.
// =============================================================
bool lerPitotMS4525(uint16_t &raw, uint8_t &status) {
  // Pede 4 bytes do sensor
  uint8_t n = Wire.requestFrom((uint8_t)MS4525_ADDR, (uint8_t)4);
  if (n < 4) {
    raw = 0;
    status = PITOT_AUSENTE;
    return false;
  }
  uint8_t b0 = Wire.read();
  uint8_t b1 = Wire.read();
  Wire.read();  // b2 (temp MSB) - descartado
  Wire.read();  // b3 (temp LSB) - descartado

  status = (b0 >> 6) & 0x03;
  raw = ((uint16_t)(b0 & 0x3F) << 8) | b1;   // 14 bits
  return true;
}

void setup() {
  Serial.begin(115200);
  while (!Serial) { ; }

  celulaEmpuxo.begin(DT_EMPUXO, SCK_EMPUXO);
  celulaTorque.begin(DT_TORQUE, SCK_TORQUE);

  pinMode(PIN_RPM, INPUT_PULLUP);

  // I2C para o Pitot
  Wire.begin();
  Wire.setClock(100000UL);  // 100 kHz, suficiente para 4 bytes em ~400 us

  // Habilita PCINT na porta D, mascara apenas o D7 (PCINT23)
  noInterrupts();
  portD_anterior = PIND;
  PCICR  |= (1 << PCIE2);            // habilita grupo PCI2 (porta D)
  PCMSK2 |= (1 << PCINT23);          // habilita interrupcao no D7
  interrupts();

  delay(200);

  // Sondagem inicial do Pitot para indicar presenca no boot
  uint16_t raw0 = 0;
  uint8_t st0 = PITOT_AUSENTE;
  lerPitotMS4525(raw0, st0);
  pitotRawCache = raw0;
  pitotStatusCache = st0;

  ultimoEnvio_us = micros();
  Serial.println(F("ID:THRUST_RIG_V3"));
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
        Serial.println(F("ID:THRUST_RIG_V3"));
        break;
      default:
        break;
    }
  }

  if (!enviando) return;

  // ---- Le Pitot (nao-bloqueante; se ausente atualiza sentinela) ----
  uint16_t pitotRaw = 0;
  uint8_t  pitotStatus = PITOT_AUSENTE;
  lerPitotMS4525(pitotRaw, pitotStatus);
  pitotRawCache = pitotRaw;
  pitotStatusCache = pitotStatus;

  // ---- Le as duas celulas (gating do envio: HX711 e o mais lento) ----
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
    Serial.print(dt_us);
    Serial.print(',');
    Serial.print(pitotRawCache);
    Serial.print(',');
    Serial.println(pitotStatusCache);
  }
}
