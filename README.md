# Bancada de Empuxo - Céu Azul Aerodesign (V2)

Sistema completo de aquisição e análise de dados para bancada de teste estático de hélice.

## O que é novo na V2

- **RPM em tempo real** via fio amarelo do ESC (interrupção no D2 do Arduino)
- **Cálculos derivados**: potência mecânica, eficiência (T/P), coeficientes adimensionais (C_T, C_P, C_Q, FOM)
- **Densidade do ar** calculada a partir de T/P/UR (CIPM-2007)
- **Calibração com hash SHA-1** para rastreabilidade — todo CSV registra o ID da calibração usada
- **Sweep manual**: detecta automaticamente patamares estáveis num CSV de ensaio onde o operador subiu o throttle em degraus
- **Banco UIUC**: parser e comparação automática com hélices de referência
- **FFT**: análise espectral com identificação de 1×RPM, BPF e harmônicas
- **SQLite**: banco de ensaios com filtros e comparação multi-ensaio
- **Monitor remoto**: servidor HTTP local para acompanhar o ensaio pelo celular
- **Detector de anomalias online**: avisa em tempo real sobre quedas de empuxo, picos de torque, oscilações de RPM
- **Relatório PDF** completo com capa, tabela de sweep, gráficos e comparação UIUC

---

## Hardware

| Item | Modelo | Notas |
|------|--------|-------|
| Microcontrolador | Arduino Nano | Pino RPM = D2 (INT0) |
| Célula empuxo | HX711 | DT=D3, SCK=D4 |
| Célula torque | HX711 | DT=D5, SCK=D6 |
| Motor | SunnySky X4120 | 14 polos = 7 pares (qualquer KV) |
| ESC | Hobbywing Platinum 120A V4 | Fio amarelo no D2 |
| Hélice atual | EOLO 16×8 | Composite, 67 g |

### Ligação do fio amarelo do ESC

O fio amarelo dos ESCs Hobbywing Platinum produz pulsos a cada comutação elétrica do motor. Como o X4120 tem 7 pares de polos, são 7 pulsos por revolução mecânica. Conecte o fio amarelo no **D2** do Arduino (pull-up interno já habilitado). Não é necessário resistor adicional.

---

## Instalação (Windows)

```bat
cd caminho\para\bancada_v2
C:\Users\<seu_usuario>\AppData\Local\Programs\Python\Python313\python.exe -m pip install pyserial numpy matplotlib pandas reportlab
C:\Users\<seu_usuario>\AppData\Local\Programs\Python\Python313\python.exe app.py
```

> Se aparecer `ModuleNotFoundError: No module named 'serial.tools'`, é porque tem um pacote conflitante instalado. Resolva com:
> ```
> python.exe -m pip uninstall serial pyserial -y
> python.exe -m pip install pyserial
> ```

---

## Fluxo de uso

### 1. Calibração (faça antes do primeiro ensaio)

1. Abra a aba **Calibração**.
2. Selecione "Empuxo" no rádio.
3. Clique **Tarar (zero)** com a célula sem carga.
4. Coloque o primeiro peso conhecido, digite o valor em gramas, escolha **subida**, clique **+ Adicionar**.
5. Repita aumentando os pesos até cobrir a faixa de uso.
6. Faça o caminho de **descida** (mesmos pesos em ordem inversa) — isso permite medir a histerese.
7. Clique **CALCULAR REGRESSÃO**.
8. Repita para "Torque".
9. Clique **Salvar**.

A calibração ganha um **ID SHA-1** que vai gravado em todo CSV daquele ensaio. Se R² < 0.99 ou histerese > 5g, o app avisa.

### 2. Coleta com sweep manual

1. Aba **Coleta** → **Conectar** na porta serial do Arduino.
2. Clique **TARA** (motor parado, sem carga).
3. Clique **▶ Novo Ensaio** → preencha os metadados (hélice, motor, bateria, condições ambientais).
4. Suba o throttle em **degraus**: ex. 30% por 8s, 50% por 8s, 70% por 8s, 90% por 6s, depois desça.
5. Use **⚑ Marcar Evento** para anotar momentos importantes (mudança de throttle, vibração estranha, etc).
6. Clique **⏹ Parar** ao terminar.
7. Clique **💾 Salvar CSV**. Salva também um JSON paralelo com metadados e indexa o ensaio no banco SQLite.

### 3. Análise

1. Aba **Análise** → **📂 Carregar CSV**.
2. **Sub-aba "Sweep"** → ajuste parâmetros (janela, limiar relativo, duração mínima) → **🔍 Detectar patamares**. O app extrai automaticamente os pontos estáveis e calcula tabela com RPM, T, Q, P_mec, T/P, C_T, C_P, FOM.
3. **Sub-aba "FFT"** → escolha um trecho estável → **🔬 Calcular FFT**. Identifica picos em 1×RPM, BPF e harmônicas.
4. **Sub-aba "UIUC"** → **🔎 Procurar hélice no UIUC**. O app busca uma hélice com mesmo diâmetro/passo no banco UIUC e plota lado a lado, calculando desvio %.
5. Clique **📋 Gerar Relatório PDF** para salvar o relatório consolidado.

### 4. Banco de ensaios

Aba **Ensaios** lista todos os ensaios indexados. Filtre por hélice/motor, selecione 2+ ensaios e clique **📊 Comparar selecionados** para sobrepor curvas.

### 5. Monitor remoto (celular)

1. Marque a caixa **Monitor remoto** no topo do app.
2. O app mostra a URL (ex: `http://192.168.0.15:8765/`).
3. Conecte o celular na **mesma rede Wi-Fi** do PC e abra a URL no navegador.

---

## Banco UIUC (opcional mas recomendado)

Para usar a comparação UIUC, baixe o banco em:
https://m-selig.ae.illinois.edu/props/propDB.html

Procure por arquivos `*_static_*.txt` e coloque em `bancada_v2/uiuc_data/`.

Para a EOLO 16×8, a referência mais próxima é a **APC 16×8E** (`apce_16x8_static_*.txt`). Geometrias muito similares.

---

## Estrutura do projeto

```
bancada_v2/
├── app.py                        # entrada principal
├── config.py                     # constantes
├── core/
│   ├── calibration.py            # CalibrationModel + regressão + histerese
│   ├── serial_reader.py          # leitor serial em thread
│   ├── derived.py                # P_mec, C_T, C_P, FOM, ρ_ar
│   ├── stable_detector.py        # detector de regime estável
│   ├── sweep_analyzer.py         # extrator de patamares de sweep manual
│   ├── anomaly.py                # detector online de anomalias
│   ├── database.py               # SQLite
│   ├── uiuc.py                   # parser do UIUC + comparação
│   ├── fft_analysis.py           # FFT com janela Hann
│   ├── remote_server.py          # HTTP server (stdlib) p/ celular
│   └── report.py                 # gerador de PDF
├── gui/
│   ├── dialogo_metadados.py      # diálogo de início de ensaio
│   ├── tab_coleta.py             # aba Coleta
│   ├── tab_calibracao.py         # aba Calibração
│   ├── tab_analise.py            # aba Análise (sweep, FFT, UIUC, PDF)
│   └── tab_ensaios.py            # aba Ensaios (SQLite)
├── firmware_arduino/
│   └── firmware_arduino.ino      # firmware V2 com RPM
├── uiuc_data/                    # ← coloque aqui os arquivos do UIUC
├── ensaios/                      # CSVs dos ensaios
├── relatorios/                   # PDFs gerados
└── config_local/                 # calibração, perfis, banco SQLite
```

---

## Convenções de cores nos plots

- **Empuxo**: azul `#1f6feb`
- **Torque**: verde `#0a8a4a`
- **RPM**: amarelo `#c08a00`
- **Potência mecânica**: vermelho `#a04040`

---

## Limites e próximos passos

**Não implementado nesta versão:**
- Tensão e corrente da bateria (sem hardware ainda)
- Comando automático do ESC para sweep automatizado (sem hardware/safety)
- Análise formal de incerteza propagada (Fase 4)

A estrutura já está preparada para receber esses módulos sem quebrar o existente.

---

## Solução de problemas

| Sintoma | Causa provável | Solução |
|---------|----------------|---------|
| RPM = 0 sempre | Fio do ESC não conectado ou no pino errado | Confira ligação no D2 |
| RPM zero apenas em rotações altas | Pulsos rápidos demais sendo perdidos | Verifique se o cabo está bem fixado, sem ruído |
| Empuxo residual depois de subir/descer | Histerese mecânica da bancada | Faça calibração subida+descida; o app mostra o valor |
| `ModuleNotFoundError: serial.tools` | Pacote `serial` (não pyserial) instalado | `pip uninstall serial pyserial -y && pip install pyserial` |
| FOM > 1 | Algum cálculo errado ou braço de torque incorreto | Confira BRACO_TORQUE_CM em config.py |
| FFT vazia | Trecho muito curto | Use trecho de pelo menos 5s |

---

Equipe Céu Azul - Aerodesign · v2.0 · 2026
