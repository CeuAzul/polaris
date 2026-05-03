# POLARIS

**P**ropeller **O**bservation, **L**ogging, **A**cquisition and **R**otation **I**nstrumentation **S**tand

> Static thrust test rig developed by **Céu Azul Aerodesign** team for characterization of propellers used in SAE Brasil Aerodesign competition aircraft.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Arduino](https://img.shields.io/badge/Arduino-Nano-00979D.svg)](https://www.arduino.cc/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)]()

---

## Overview

POLARIS is a complete acquisition and analysis system for static propeller testing. It captures thrust, torque, and RPM in real time from a custom mechanical bench, performs traceable multi-point calibration, automatically extracts steady-state operating points from manual throttle sweeps, computes non-dimensional aerodynamic coefficients (C_T, C_P, C_Q, FOM), and generates publication-ready PDF reports with cross-reference to the UIUC Propeller Database.

The system was designed around three principles:

- **Traceability** — every measurement carries the calibration ID (SHA-1 hash) and full ambient metadata
- **Repeatability** — automatic detection of steady regimes, hysteresis tracking, and online anomaly detection
- **Practicality** — single-click setup, mobile remote monitor, and one-click PDF report generation

---

## Table of Contents

- [Features](#features)
- [Hardware](#hardware)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [User Guide](#user-guide)
  - [1. Calibration](#1-calibration)
  - [2. Data Collection](#2-data-collection)
  - [3. Analysis](#3-analysis)
  - [4. Test Database](#4-test-database)
  - [5. Remote Monitor](#5-remote-monitor)
- [Technical Details](#technical-details)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [License](#license)

---

## Features

### Acquisition
- **Real-time data streaming** from Arduino via USB serial (115200 baud)
- **Two HX711 load cells** for thrust and torque measurement
- **RPM via ESC signal wire** using Pin Change Interrupt with debounce filtering
- **Multi-point calibration** with mandatory up/down sweep for hysteresis quantification
- **Automatic tare** before each test
- **Configurable moving-average filter** (1–200 samples)

### Analysis
- **Manual sweep extraction** — automatically detects stable plateaus in a CSV from a manual throttle sweep
- **Non-dimensional coefficients** — C_T, C_P, C_Q, Figure of Merit (FOM)
- **FFT spectral analysis** — identifies 1×RPM (imbalance), BPF (blade-pass frequency) and harmonics
- **UIUC database integration** — automatic lookup and side-by-side comparison with reference data
- **Online anomaly detector** — warns about thrust drops, torque spikes, and RPM oscillations during the test

### Outputs
- **CSV with full metadata** (propeller, motor, battery, ambient conditions, calibration ID, marked events)
- **Parallel JSON file** with structured metadata
- **PDF report** with cover page, calibration summary, sweep table, performance plots, and UIUC comparison
- **SQLite database** indexing all tests for filtering and multi-test comparison
- **Mobile remote monitor** — HTTP page accessible from any device on the same Wi-Fi

---

## Hardware

### Bill of Materials

| Component | Model | Notes |
|-----------|-------|-------|
| Microcontroller | Arduino Nano | ATmega328P, 16 MHz |
| Thrust load cell | 10 kg with HX711 | DT=D3, SCK=D4 |
| Torque load cell | 5 kg with HX711 | DT=D5, SCK=D6 |
| RPM sensor | ESC yellow signal wire | D7 (PCINT23) |
| Motor | Any | 14 poles = 7 pole pairs |
| ESC | Hobbywing Platinum V4 | RPM signal output via yellow wire |
| Propeller | Any | Configurable in test metadata |

### Wiring Diagram

```
Arduino Nano               ESC                       Battery
─────────────              ─────                     ───────
   D2 ───────── (free)
   D3 ─── DT  ┐
   D4 ─── SCK ┤ HX711 #1 (thrust)
   D5 ─── DT  ┐
   D6 ─── SCK ┤ HX711 #2 (torque)
   D7 ────────────────── Yellow (RPM signal)
   GND ───────────────── Black (BEC GND)        ←── CRITICAL: shared ground
   5V ── (USB powered, NOT from BEC)
   USB ── PC
                          Red ── (BEC +5V, NOT connected to Arduino)
                          White ── Receiver throttle channel
```

> ⚠️ **CRITICAL**: The Arduino ground MUST be connected to the ESC ground (BEC black wire or battery negative terminal). Without a common ground, the RPM signal will be unstable and produce nonsensical readings. **DO NOT** connect the BEC red wire (+5V) to the Arduino — the Arduino is powered by USB.

### Mechanical Setup

The bench uses an aluminum profile structure with a sliding carriage that pulls a horizontally mounted thrust load cell via a threaded rod. The motor mount is connected to a torque arm whose force is captured by the second load cell. The default torque arm length is 7 cm (configurable in `config.py`).

> 📷 **TODO**: Add photos of the assembled bench in `docs/photos/` and reference them here:
> ```markdown
> ![Bench overview](docs/photos/bench_overview.jpg)
> ![Wiring detail](docs/photos/wiring.jpg)
> ```

---

## Installation

### Prerequisites

- **Python 3.10 or newer** (tested on 3.10–3.13)
- **Arduino IDE** (1.8 or 2.x) for firmware upload
- **CH340 USB driver** for clone Arduino Nano boards ([download here](https://www.wch-ic.com/downloads/CH341SER_EXE.html))

### Software setup

```bash
# Clone the repository
git clone https://github.com/ceuazul/polaris.git
cd polaris

# Install Python dependencies
pip install pyserial numpy matplotlib pandas reportlab
```

> **Windows note**: if you get `ModuleNotFoundError: No module named 'serial.tools'`, you have a conflicting package. Fix with:
> ```
> pip uninstall serial pyserial -y
> pip install pyserial
> ```

### Firmware upload

1. Open `firmware_arduino/firmware_arduino.ino` in the Arduino IDE
2. Select **Board**: Arduino Nano
3. Select **Processor**: ATmega328P (try "Old Bootloader" if upload fails)
4. Select the correct **Port**
5. Click **Upload**

You should see in the Serial Monitor (115200 baud) the line `ID:THRUST_RIG_V2` confirming the firmware is running.

### Optional: UIUC Propeller Database

For comparison with reference data, download files from the [UIUC Propeller Database](https://m-selig.ae.illinois.edu/props/propDB.html) and place the `*_static_*.txt` files in the `uiuc_data/` folder.

### Run the application

```bash
python app.py
```

---

## Quick Start

```
1. Calibrate thrust and torque cells (one-time setup)
        ↓
2. Connect the rig (Arduino → USB → PC)
        ↓
3. Tare (with motor stopped)
        ↓
4. Click "▶ New Test", fill metadata
        ↓
5. Run the throttle in steps (e.g., 30%, 50%, 70%, 90%, then back down)
        ↓
6. Stop, save CSV
        ↓
7. Go to Analysis tab → Detect plateaus → Generate PDF
```

---

## User Guide

The application has four main tabs:

| Tab | Purpose |
|-----|---------|
| 📊 **Coleta** (Collection) | Real-time acquisition with live plots |
| ⚖ **Calibração** (Calibration) | Multi-point load cell calibration |
| 🔬 **Análise** (Analysis) | Sweep extraction, FFT, UIUC comparison, PDF |
| 🗂 **Ensaios** (Tests) | SQLite database of all tests |

### 1. Calibration

Calibration is **mandatory before the first test** and recommended periodically.

**Procedure:**

1. Open the **Calibração** tab
2. Select **Empuxo** (thrust) radio button
3. Click **Tarar (zero)** with no load on the cell
4. Place the first known weight (e.g., 500 g), enter the value, select **subida** (going up), click **+ Adicionar Ponto**
5. Repeat with increasing weights until covering the expected range (typical: 0, 500, 1000, 2000, 3000, 5000, 7000 g)
6. Now do the **down** sweep: remove weights in reverse order, switching the direction selector to **descida**
7. Click **📊 CALCULAR REGRESSÃO**
8. Repeat steps 2–7 selecting **Torque** instead
9. Click **💾 Salvar**

**Why up AND down?** Mechanical structures exhibit **hysteresis** — the reading at 1000 g going up is not exactly the same as 1000 g coming down. The difference quantifies the irreducible measurement uncertainty of your bench. Quality criteria:

- **R² ≥ 0.999** → Good
- **Hysteresis < 5 g** → Good
- **R² < 0.99 or hysteresis > 20 g** → Mechanical issues (loose screws, friction, misalignment) — fix before testing

Each calibration receives a **SHA-1 ID hash** that is permanently recorded in every CSV file produced afterward, ensuring full traceability.

### 2. Data Collection

**Before connecting the battery:**

1. Connect the Arduino to the PC via USB
2. Click **Conectar** in the Coleta tab; status should turn green
3. Click **TARA** with the motor mounted but not running

**To start a test:**

1. Click **▶ Novo Ensaio**
2. Fill in the metadata dialog:
   - **Propeller**: pick a preset or enter manually
   - **Motor**: pick a preset — pole pairs default to 7
   - **Battery**: cells, capacity (mAh), initial voltage
   - **Ambient conditions**: temperature, pressure, humidity → click **Calcular rho** to compute air density (CIPM-2007 formula)
   - **Operator** and notes
3. Click OK — collection starts immediately

**During the test:**

- The plot shows thrust, torque, and RPM in three stacked panels
- Numeric indicators show filtered values plus derived quantities (P_mec, T/P, C_T, FOM)
- The "REGIME" label shows whether the signal is steady (green) or transient (orange)
- A configurable moving average smooths the live plot (does not affect saved data)
- **Anomaly detector** displays warnings if it detects sudden thrust drops, torque spikes, or RPM oscillations
- Click **🗑 Limpar Gráficos** anytime to reset the plot view (raw data is preserved)
- Click **⚑ Marcar Evento** to mark a timestamp with a label (e.g., "throttle 50%", "vibration started")

**Manual sweep procedure:**

For sweep analysis to work later, you need to hold each throttle level **constant for at least 6 seconds** before changing. A typical pattern:

```
0%  →  30% (8s)  →  50% (8s)  →  70% (8s)  →  90% (6s)  →
50% (8s)  →  30% (8s)  →  0%
```

**Stopping and saving:**

1. Click **⏹ Parar** when done
2. Click **💾 Salvar CSV**, choose location
3. The system saves three things:
   - `ensaio_<name>_<timestamp>.csv` — full time series with all derived values
   - `ensaio_<name>_<timestamp>.json` — structured metadata
   - The test is automatically indexed in the SQLite database

### 3. Analysis

In the **Análise** tab:

1. Click **📂 Carregar CSV** and pick the test file
2. The full time series is plotted automatically

**Sub-tabs:**

#### Sweep (steady plateaus)

Automatically extracts stable operating points from a manual sweep.

- Adjust **Janela (s)** = window size for std-dev calculation (default 2.0s)
- Adjust **Lim relativo** = relative threshold (3% of local mean by default)
- Adjust **Min dur (s)** = minimum plateau duration to be counted (default 1.5s — increase to 4s for cleaner results)
- Choose **Sinal-base** = `empuxo_g` (thrust-based detection) or `rpm` (RPM-based, often cleaner)
- Click **🔍 Detectar patamares**

The table fills with one row per detected plateau, showing mean ± std for thrust, torque, RPM, plus computed P_mec, T/P, C_T, C_P, FOM. Four small plots show the curves vs RPM.

Click **💾 Exportar tabela** to save just the sweep results as CSV.

#### FFT / Spectrum

Spectral analysis of a chosen time segment.

- Set **t inicial** and **Duração** (recommend at least 5s in a steady region)
- Click **🔬 Calcular FFT**

The plot shows magnitude vs frequency for thrust and torque. Vertical red lines mark expected peaks (1×RPM, BPF, harmonics) based on the average RPM in the segment and 2 propeller blades (configurable in code).

#### UIUC

Cross-reference with the UIUC Propeller Database.

- Adjust **Tolerância (in)** if your propeller diameter/pitch doesn't exactly match a database entry
- Click **🔎 Procurar hélice no UIUC**

The system searches for a matching propeller (preferring APC, falling back to any manufacturer), parses the static-test file, and shows side-by-side C_T and C_P plots with deviation percentages in a table.

> Note: UIUC data is mostly for APC propellers. For non-APC propellers like EOLO, deviations of 15–30% are normal due to geometric differences.

#### PDF report

Click **📋 Gerar Relatorio PDF** to export everything as a multi-page PDF:

- Cover page with full configuration
- Calibration summary with quality assessment
- Sweep table with all extracted points
- Six performance plots (T, Q, P_mec, T/P, C_T, FOM vs RPM)
- UIUC comparison if loaded
- Operator notes

### 4. Test Database

The **Ensaios** tab shows all tests indexed in the SQLite database (`config_local/ensaios.db`).

- Filter by propeller or motor name
- Click headers to sort
- Select 2+ tests and click **📊 Comparar selecionados** to overlay their curves on a chosen Y-axis

This is essential for comparing propellers, motors, or pre/post-modification configurations.

### 5. Remote Monitor

To monitor the test from a phone or tablet on the same Wi-Fi:

1. Check the **Monitor remoto** box in the top toolbar
2. The app shows a URL like `http://192.168.0.15:8765/`
3. Open this URL on the phone's browser

The remote view shows the four main numbers (thrust, torque, RPM, P_mec) in large fonts plus a steady-regime indicator, updating twice per second. Useful for keeping the operator at a safe distance from the spinning propeller.

---

## Technical Details

### RPM measurement

The Hobbywing Platinum ESC outputs one electrical commutation pulse per electrical revolution on the yellow wire. For a motor with N pole pairs, the conversion is:

```
RPM_mechanical = (pulses_per_second × 60) / pole_pairs
```

The Arduino uses Pin Change Interrupt (PCINT23 on D7) with a 400 µs software debounce to filter ESC switching noise.

### Air density (CIPM-2007 formula)

```
ρ = (P_dry / R_dry × T) + (P_vapor / R_vapor × T)

where:
  P_vapor = RH × 611.2 × exp(17.62 × T / (243.12 + T))
  P_dry   = P_total - P_vapor
  R_dry   = 287.058 J/(kg·K)
  R_vapor = 461.495 J/(kg·K)
  T       in Kelvin
```

Typical accuracy: ±0.1%. Sufficient for aerodynamic coefficient calculations.

### Non-dimensional coefficients (static, J = 0)

```
n = RPM / 60        [rev/s]
T = thrust          [N]
Q = torque          [N·m]
P_mec = 2π × n × Q  [W]

C_T = T / (ρ × n² × D⁴)
C_P = P_mec / (ρ × n³ × D⁵)
C_Q = Q / (ρ × n² × D⁵)
FOM = C_T^1.5 / (C_P × √2)         (Figure of Merit, ideal hover)
```

Note: FOM > 1 is physically impossible (Betz limit). If observed, indicates measurement error in either thrust (too high) or torque (too low).

### Calibration model

Linear least-squares fit:

```
raw_count = A × weight + B
weight    = (raw_count - B) / A
```

Hysteresis is computed point-by-point as the difference between the predicted weight on the up vs down sweep.

### Stable-plateau detection (offline)

1. For each sample, compute rolling std-dev in a window of size `janela_s`
2. Mark as stable where `std < max(local_mean × limiar_rel, 5 g)`
3. Group consecutive stable samples into plateaus
4. Discard plateaus shorter than `min_dur_s`
5. Trim 0.4s from each plateau edge to avoid transients
6. Compute mean and std of each channel inside the plateau

### Anomaly detection (online)

Three heuristics with 3s cooldown:

1. **Thrust drop**: thrust falls > 15% over baseline (10s window) → possible blade damage
2. **Torque spike**: torque rises > 30% without proportional thrust increase → possible stall
3. **RPM oscillation**: RPM std/mean > 20% in last second → mechanical or ESC issue

---

## Project Structure

```
polaris/
├── app.py                        # Application entry point
├── config.py                     # Constants and paths
├── core/
│   ├── calibration.py            # CalibrationModel + regression + hysteresis
│   ├── serial_reader.py          # Threaded serial reader
│   ├── derived.py                # P_mec, C_T, C_P, FOM, ρ_air
│   ├── stable_detector.py        # Online + offline plateau detector
│   ├── sweep_analyzer.py         # Manual sweep extraction
│   ├── anomaly.py                # Online anomaly detector
│   ├── database.py               # SQLite layer
│   ├── uiuc.py                   # UIUC parser + comparison
│   ├── fft_analysis.py           # FFT with Hann window
│   ├── remote_server.py          # HTTP server for mobile monitor
│   └── report.py                 # PDF generator
├── gui/
│   ├── dialogo_metadados.py      # Test setup dialog
│   ├── tab_coleta.py             # Collection tab
│   ├── tab_calibracao.py         # Calibration tab
│   ├── tab_analise.py            # Analysis tab
│   └── tab_ensaios.py            # Tests database tab
├── firmware_arduino/
│   └── firmware_arduino.ino      # Arduino firmware
├── uiuc_data/                    # ← place UIUC database files here
├── ensaios/                      # CSV outputs (auto-created)
├── relatorios/                   # PDF outputs (auto-created)
├── config_local/                 # calibration, profiles, SQLite DB (auto-created)
└── README.md
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `ModuleNotFoundError: No module named 'serial.tools'` | Conflicting `serial` package | `pip uninstall serial pyserial -y && pip install pyserial` |
| `module 'serial' has no attribute 'Serial'` | Same as above | Same fix |
| Arduino upload fails with "not in sync" | CH340 driver missing or USB cable is power-only | Install CH340 driver; try a different USB cable |
| RPM always 0 | Yellow wire not connected or no common ground | Check D7 wiring; **verify ground is shared between Arduino and ESC** |
| RPM erratic / 100x too high | No common ground | **Connect Arduino GND to ESC BEC ground (black wire)** |
| RPM doubled or halved | Wrong pole pairs in metadata | SunnySky X4120 = 7 pairs; check motor specs |
| FOM > 1 | Torque measured too low or thrust too high | Check torque arm coupling, recalibrate, verify arm length in `config.py` |
| Massive hysteresis (>50 g) | Mechanical issues | Tighten screws, check carriage friction, align thrust cell |
| Sweep detector finds spurious plateaus at start/end | Default min duration too short | Increase **Min dur (s)** to 4–5 s |
| App runs but plot is empty | No data flowing | Check serial monitor first to confirm Arduino is sending; click TARA after connecting |

---

## Roadmap

Planned for future versions:

- [ ] Voltage and current acquisition (INA226 or similar)
- [ ] Automated throttle sweep with safety interlocks
- [ ] Formal uncertainty propagation (GUM-compliant)
- [ ] Vibration measurement (accelerometer integration)
- [ ] Real-time efficiency mapping (T/P heatmap vs RPM/throttle)

---

## License

MIT License — see [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- **Céu Azul Aerodesign** team (UFSC, Brazil) for the bench design and testing
- **University of Illinois at Urbana-Champaign** for the publicly available [Propeller Database](https://m-selig.ae.illinois.edu/props/propDB.html)

---

<p align="center">
  <i>POLARIS</i><br>
  <b>Céu Azul Aeronaves · Advanced 2026</b>
  Made by <a href="https://github.com/higor0227">@higor0227</a> and <a href="https://github.com/joaoheck">@joaoheck</a>
</p>


 
