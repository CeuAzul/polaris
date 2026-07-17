# POLARIS — Project Context & Decision Log

> **Para Claude (ou qualquer LLM) que abrir este repositório:**
> Este documento captura o raciocínio, decisões técnicas e problemas em aberto do projeto. Leia este arquivo ANTES de fazer mudanças significativas. Ele complementa o README.md (que descreve o que o sistema faz) explicando *por que* as coisas estão como estão.

---

## Sumário

- [Sobre o projeto](#sobre-o-projeto)
- [Hardware definido](#hardware-definido)
- [Decisões arquiteturais importantes](#decisões-arquiteturais-importantes)
- [Decisões físicas/numéricas críticas](#decisões-físicasnuméricas-críticas)
- [Problemas resolvidos (histórico)](#problemas-resolvidos-histórico)
- [Problemas em aberto](#problemas-em-aberto)
- [Próximos passos planejados](#próximos-passos-planejados)
- [Convenções de código](#convenções-de-código)
- [Estilo de comunicação preferido](#estilo-de-comunicação-preferido)

---

## Sobre o projeto

POLARIS é a bancada de teste estático de hélices da equipe **Céu Azul Aerodesign** (UFSC). Foi desenvolvida especificamente para caracterizar a hélice **EOLO 16x8 + motor SunnySky X4120** usados em competição SAE Brasil Aerodesign.

O projeto começou de uma versão monolítica em Python com Arduino básico (V1) e foi refatorado em V2 modular com 23 arquivos organizados em `core/` e `gui/`.

---

## Hardware definido

| Item | Modelo | Notas |
|------|--------|-------|
| MCU | Arduino Nano (ATmega328P) | A PCB já está montada, **não dá para mover pinos facilmente** |
| Célula empuxo | HX711 + célula 10kg | DT=D3, SCK=D4 |
| Célula torque | HX711 + célula 5kg | DT=D5, SCK=D6 |
| **RPM** | **D7** (PCINT23) | NÃO é INT0/INT1 — usa Pin Change Interrupt |
| **Pitot** | **MS4525DO** | I2C: SDA=A4, SCL=A5; endereço 0x28; ±1 psi; alimentação 3.3V |
| Motor | SunnySky X4120 KV480 | **7 pares de polos** (todas as versões KV) |
| ESC | Hobbywing Platinum 120A V4 | Fio amarelo = sinal de RPM |
| Hélice | EOLO 16x8 (composite) | Sem dados públicos detalhados |

### Por que D7 e não D2?

A PCB foi montada com o D2 inacessível fisicamente. O usuário pediu D7 explicitamente. Implementação usa **Pin Change Interrupt no PCMSK2**, com performance idêntica a INT0/INT1. **Não tente mover de volta para D2 sem confirmar com o usuário.**

### Por que MS4525DO para o Pitot?

Sensor escolhido porque: (1) disponível na equipe, (2) I2C → apenas 2 fios além de power/GND, (3) range ±1 psi (~±6894 Pa) cobre a faixa 0–25 m/s com boa resolução de 14 bits, (4) comunicação direta com Arduino sem circuito externo.

**Derivação do pa_per_count:**
```
Range total = 2 × 6894.76 Pa  (±1 psi)
Contagens úteis (Type B): count_max = 15565, count_min = 819
pa_per_count = 2 × 6894.76 / (15565 - 819) ≈ 0.9352 Pa/count

Contagens úteis (Type A): count_max = 14746, count_min = 1638
pa_per_count = 2 × 6894.76 / (14746 - 1638) ≈ 1.0520 Pa/count
```

Verificar o tipo (A ou B) no datasheet do módulo específico. A maioria dos módulos DS3AI/DS3TI são Type B. A diferença é ~12% — importante acertar.

---

## Decisões arquiteturais importantes

### 1. Modularidade

V2 foi reorganizada em módulos pequenos:
- `core/` — lógica pura sem dependência de GUI (calibração, cálculos, parsers, banco)
- `gui/` — interface tk/ttk separada, uma aba por arquivo
- `firmware_arduino/` — firmware do MCU
- `app.py` — apenas orquestra (instancia App, conecta sinais)

**Princípio:** qualquer funcionalidade nova começa como função em `core/`, depois ganha integração na GUI. Isso permite testar lógica sem precisar de hardware.

### 2. Rastreabilidade total

Todo CSV salvo carrega:
- Header com `#` linhas contendo metadados
- `cal_id` (hash SHA-1 da calibração ativa) gravado em cada CSV
- JSON paralelo com metadados estruturados
- Indexação automática no SQLite

**Por quê:** em ensaios de competição, é fundamental saber exatamente qual versão da calibração gerou cada número. O hash determinístico permite auditoria completa.

### 3. Sweep manual ao invés de automatizado

Por **decisão explícita do usuário**, NÃO implementamos comando automático de throttle. O sweep é manual: operador sobe throttle em degraus, e o app extrai patamares estáveis offline.

**Motivo:** segurança. Sem hardware de safety interlock, comandar ESC automaticamente é arriscado.

### 4. Sem suporte a tensão/corrente ainda

Por **decisão do usuário** (V2 inicial), V/I foram excluídos porque não tinham hardware. **Está planejado para V3** com INA226. Não tente adicionar antes de coordenar.

### 5. Detector de regime estável online + offline

Tem dois modos:
- **Online** (`StableDetector`): usado durante coleta para indicador visual de "regime estável"
- **Offline** (`detectar_patamares` em `stable_detector.py`): usado pelo sweep_analyzer para extração pós-ensaio

Ambos compartilham a mesma lógica conceitual mas com parâmetros diferentes. **Não unifiquem sem necessidade.**

---

## Decisões físicas/numéricas críticas

### RPM — Fórmula correta

```python
RPM_mecanico = (pulsos_por_segundo × 60) / pares_polos
```

Para o X4120 com 7 pares de polos:
```
RPM_mec = pulsos/s × 60 / 7
```

**Esta fórmula passou por iterações:**

1. **Tentativa 1:** dividir por `pares_polos` (= 7) → primeiro ensaio deu RPM absurdo (200.000)
2. **Tentativa 2:** após adicionar GND comum, ainda parecia errado, mudei para `× 2 / pares_polos` (= dividir por 3.5) baseado em interpretação do manual e medição com tacômetro de celular
3. **Tentativa 3 (atual):** validação contra UIUC mostrou que dividir por 7 dá empuxos coerentes. **A fórmula correta é dividir por 7**, e o tacômetro de celular tinha erro (provavelmente contou BPF da hélice = 2× RPM real).

**Lição aprendida:** validar RPM com **tacômetro óptico de verdade** (TC-5035 que vocês têm), não confiar em apps de celular.

### Densidade do ar — CIPM-2007

Usamos a fórmula CIPM-2007 simplificada (precisão ~0.1%) — suficiente para coeficientes adimensionais. **Não trocar por ISA pura**, porque vocês precisam medir condições reais (temperatura/pressão/umidade do galpão).

### Coeficientes adimensionais — fórmulas estáticas (J=0)

```
n      [rev/s] = RPM / 60
T      [N]     = empuxo_g × g / 1000
Q      [N·m]   = forca_torque_g × g / 1000 × braco_m
P_mec  [W]     = 2π × n × Q

C_T = T / (ρ × n² × D⁴)
C_P = P_mec / (ρ × n³ × D⁵)
C_Q = Q / (ρ × n² × D⁵)
FOM = C_T^1.5 / (C_P × √2)
```

**Limite físico:** FOM > 1 é impossível (limite de Betz). Se aparecer no resultado, é erro de medição.

### Coeficientes adimensionais — fórmulas dinâmicas (J > 0, com Pitot)

```
q_pa [Pa] = (raw_pitot - raw_offset) × pa_per_count × k_corr
V_ms [m/s] = √(2 × q_pa / ρ)   — válido apenas para V < 30 m/s (incompressível)

J   = V / (n × D)              — razão de avanço; 0 em hover, ~1 em stall
η   = J × C_T / C_P            — eficiência da hélice (típico máximo 0.70–0.85)
```

**FOM vs η:** são métricas distintas. FOM é adequada para rotor em hover (J≈0, tipo quadricóptero). η é adequada para hélice propulsiva em voo (J>0). Para uso em asa fixa (APC, EOLO), a métrica correta é η. Mantemos FOM no CSV por compatibilidade, mas o relatório dinâmico prioriza η.

### Protocolo serial V2 vs V3

| Versão | Campos por linha | Firmware ID |
|--------|-----------------|-------------|
| V2 | `raw_e,raw_t,pulsos,dt_us` | `THRUST_RIG_V2` |
| V3 | `raw_e,raw_t,pulsos,dt_us,raw_pitot,status_pitot` | `THRUST_RIG_V3` |

O `serial_reader.py` detecta a versão pelo número de campos — 4 = V2, 6 = V3. Em V2 injeta `raw_pitot=0, status_pitot=4` (ausente). Todos os consumidores recebem 7-tupla `(t, raw_e, raw_t, pulsos, dt_us, raw_pitot, status_pitot)`. **Não adicione campos ao protocolo sem atualizar o parser e TODOS os consumidores.**

### Modo dinâmico — restrições de uso

1. **V < 30 m/s** — pressão dinâmica calculada por fórmula incompressível; acima disso erro de compressibilidade > 1%
2. **Pitot upstream** — o tubo deve apontar para o escoamento livre do túnel, ANTES do disco da hélice. Instalar a jusante contamina a leitura com a esteira propulsiva
3. **Tara a cada sessão** — offset de pressão deriva com temperatura. Semrpre fazer tara com túnel desligado antes de iniciar
4. **Estabilidade dupla** — sweep em modo dinâmico exige que TANTO o empuxo QUANTO a velocidade estejam estáveis simultaneamente (interseção das máscaras). Se o detector encontrar 0 patamares, verificar estabilidade do controlador do túnel

### Braço de torque

Default `BRACO_TORQUE_CM = 7.0` em `config.py`. **Confirmar com o usuário antes de mudar** — é parâmetro mecânico da bancada física.

### Conversão N.cm → N.m

A V2 inicial usava N.cm em várias partes. **Foi migrado para N.m em todos os displays e gráficos** por decisão do usuário. O CSV mantém ambas as colunas (`torque_Nm` e `torque_Ncm`) para compatibilidade.

---

## Problemas resolvidos (histórico)

### 1. Histerese mecânica original

**Sintoma:** ao zerar a célula após teste, sobrava empuxo residual. Calibração com R² alto mas histerese de >450g.

**Diagnóstico:** atrito mecânico no carrinho/parafuso da bancada + acoplamento entre braço de torque e célula com atrito metal-metal.

**Solução parcial:** calibração multipontos com subida + descida para quantificar histerese. Aviso visual na qualidade da calibração.

**Solução completa (a fazer):** ver "Problemas em aberto".

### 2. RPM dando 200.000 (e depois 110 Hz constante)

**Causa raiz:** **GND não compartilhado** entre Arduino e ESC.

**Sintoma inicial:** valores absurdos de RPM
**Sintoma após debounce:** 110 Hz constante mesmo com motor parado (ruído elétrico de modo comum sem referência de GND)

**Solução:**
- **Conectar fio preto do BEC do ESC ao GND do Arduino** (CRÍTICO)
- NÃO conectar o fio vermelho (+5V do BEC) — Arduino é alimentado por USB
- Adicionado debounce de 400µs no firmware como margem

**Marco no README e Troubleshooting:** este foi o problema mais difícil de debugar, está documentado em destaque.

### 3. Erro `module 'serial' has no attribute 'Serial'`

**Causa:** pacote Python `serial` (genérico, errado) instalado conflitando com `pyserial` (correto).

**Solução documentada no README:**
```
pip uninstall serial pyserial -y
pip install pyserial
```

### 4. Upload Arduino "not in sync: resp=0x00"

**Causa típica:** driver CH340 não instalado (Arduino Nano clone usa esse chip USB-serial).

**Solução:** instalar driver de https://www.wch-ic.com/downloads/CH341SER_EXE.html

### 5. Patamares espúrios no sweep

**Sintoma:** detector pegava regiões antes/depois do motor girar como "patamares estáveis", contaminando a tabela.

**Solução:** sweep_analyzer.py recebeu parâmetro `min_dur_s` (recomendado 4s) e o usuário aprende a aumentar via GUI.

**Possível melhoria futura:** filtrar automaticamente patamares com `RPM < 500`.

---

## Problemas em aberto

### 🔴 1. Atrito no acoplamento da célula de torque (CRÍTICO)

**Estado:** identificado pela foto da bancada. A chapa de alumínio do braço de torque apoia **direto sobre a célula** com contato metal-metal, gerando atrito significativo.

**Evidência numérica:**
- C_P do ensaio = 0.0122 vs UIUC APC = 0.0287 → **57% subestimado**
- FOM > 1 nos pontos de RPM alto (1.115, 1.266) → fisicamente impossível
- Histerese de torque de 215g na calibração

**Solução proposta (não implementada):** colocar **esfera de aço de 5-10mm** entre a chapa e a célula, com cavidades cônicas em ambas as superfícies. A esfera transmite só força axial, eliminando atrito tangencial.

**Alternativas:** lâmina flexível (flexure), rolamento linear, pivô knife-edge.

### 🟡 2. C_T sistematicamente 30% abaixo do UIUC

**Estado:** mesmo após correção da densidade (ρ=1.225), o C_T do ensaio fica ~30% abaixo da APC 16x8E.

**Hipóteses:**
1. Diferença real EOLO vs APC (esperaríamos 10-20%, não 30%)
2. Atrito mecânico no carrinho de empuxo também engolindo força (similar ao do torque)
3. Comprimento real do braço de torque ≠ 7cm declarado

**Próximo teste:** **puxar o carrinho da bancada com peso conhecido** (ex: garrafa de 1.5kg suspensa por corda) e ver se o app lê o valor correto. Se ler menos, confirma atrito no carrinho de empuxo.

### ✅ 3. Validação de RPM com tacômetro óptico — RESOLVIDO

**Estado:** RPM validado com tacômetro óptico TC-5035. A fórmula `RPM_mec = pulsos/s × 60 / pares_polos` está confirmada. Para o SunnySky X4120 com 7 pares de polos, dividir por 7 dá o valor correto. **Não alterar a fórmula.**

### 🟢 4. Calibração com qualidade ruim

**Estado:** R² de 0.996 (limite aceitável) mas histerese de 454g (empuxo) e 215g (torque). **Refazer com cuidado** após resolver o atrito do torque.

---

## Próximos passos planejados

### Curto prazo (semanas)

1. **Resolver atrito do torque** (esfera de aço) — bloqueador para dados confiáveis
2. **Refazer calibração** com bancada apertada e alinhada
3. **Validar RPM com TC-5035** — fechar a dúvida de uma vez
4. **Repetir ensaio EOLO 16x8** após (1)-(3) para ver se C_P/FOM ficam coerentes

### Médio prazo (semanas/meses)

5. **Ensaios em túnel de vento com Pitot** — hardware já integrado (V3). Primeiro ensaio dinâmico real para validar J e η contra UIUC dinâmico
6. **Adicionar tensão e corrente (V/I)** com INA226 — fecha o triângulo de potência:
   - Hardware: INA226 + shunt 75mV/100A, comunicação I2C
   - Firmware: leitura I2C adicionada ao loop principal (cuidado: I2C já está em uso pelo Pitot no mesmo bus — endereços compatíveis: INA226=0x40, MS4525=0x28)
   - App: novos campos no CSV (`v_bat`, `i_bat`, `p_eletrica`, `eficiencia_motor`)
   - Dialog: campos extras nos metadados
   - PDF: seção adicional com curvas elétricas
7. **Comprar APC 16x8E real** para validação cruzada (custa ~80 reais, permite calibrar offset sistemático contra UIUC)
8. **Análise de incerteza propagada** (GUM-compliant) — usar histerese e R² da calibração para propagar até C_T, C_P, FOM

### Longo prazo (semestre)

8. **Análise de degradação** de hélice (mesma EOLO antes/depois de N ensaios)
9. **Vibração estrutural** com MPU6050 + integração com FFT já existente
10. **Banco interno** da equipe com vários ensaios EOLO/SunnySky para tomada de decisão técnica
11. **Sweep automatizado** com safety interlocks (apenas DEPOIS de V/I implementado)

### Tópicos que NÃO devem ser implementados sem coordenação

- **Comando direto do ESC** (sweep automatizado) — questão de segurança
- **Mudanças no protocolo serial** do firmware — quebra compatibilidade com CSVs antigos
- **Alteração de fórmulas de cálculo** já validadas — só com nova evidência empírica

---

## Convenções de código

### Python
- Python 3.10+ (testado em 3.13)
- Tipagem leve com hints onde ajuda legibilidade
- Dataclasses para estruturas de dados
- **Sem acentos no código** (comentários ok com cuidado, código sem)
- Comentários em **português** — equipe brasileira, primeiros usuários BR
- Strings de UI em português
- Cores consistentes nos plots:
  - Empuxo: `#1f6feb` (azul)
  - Torque: `#0a8a4a` (verde)
  - RPM: `#c08a00` (amarelo)
  - P_mec: `#a04040` (vermelho)

### Arduino
- C++ Arduino padrão
- Comentários em português
- Constantes em UPPER_SNAKE_CASE com `#define`
- Variáveis em camelCase
- ISRs **mínimas** — só incrementar contador, sem prints, sem cálculo

### Git (após migração para Claude Code)
- Commits em português, mensagem objetiva no imperativo
- Branches por feature (`feature/v_i_sensor`, `fix/torque_friction`)
- Tags para versões de competição (`v2.0-sae2026`)

### Estrutura de diretórios
- **Não criar pastas vazias com `.gitkeep`** sem necessidade
- **Não commitar** arquivos em `config_local/`, `ensaios/`, `relatorios/` (são gerados em runtime, devem entrar no .gitignore)
- **Sim commitar** o `uiuc_data/` se vocês baixaram dados específicos para o projeto

---

## Estilo de comunicação preferido

O usuário (Higor / equipe Céu Azul):

- **Português brasileiro**
- Trabalha em **sprints intensos** — quer testar mudanças no mesmo dia
- Valoriza **explicação do raciocínio** antes da implementação, principalmente em decisões importantes
- **Não gosta de surpresas** — prefere ver o plano antes de eu começar a codar muita coisa
- Aprecia **diagnóstico lógico** quando algo dá errado (hipóteses → teste → conclusão)
- Aceita bem **respostas diretas e críticas técnicas** quando há erro real (não amenize, fale o que está errado)
- Faz testes empíricos e manda dados em CSV/log — analise os números antes de chutar causas
- Conhece bem aerodinâmica e mecânica, mas é **júnior em software** — explique conceitos de programação quando relevantes
- Tem **acesso à equipe** (UFSC) que pode validar partes mecânicas

### O que evitar

- Implementar muita coisa de uma vez sem checkpoint
- Adicionar features que não foram pedidas
- Ser excessivamente verboso em explicações simples
- Usar emojis em excesso
- Mudar fórmulas físicas sem justificativa empírica clara

### O que fazer

- Antes de mudanças grandes: **explicar o plano** e pedir aprovação
- Antes de hipóteses sobre problemas: **olhar os dados reais** que o usuário enviou (CSVs, fotos, logs)
- Quando der errado: **assumir o erro** sem floreio, propor solução
- Para problemas físicos/mecânicos: pedir foto e medir com cuidado antes de chutar

---

## Arquivos importantes para inspecionar primeiro

Se você é um novo Claude entrando neste projeto, recomendo nesta ordem:

1. `README.md` — visão geral
2. `CONTEXT.md` (este arquivo) — decisões e problemas em aberto
3. `config.py` — constantes do sistema
4. `core/derived.py` — fórmulas físicas (RPM, P_mec, C_T, C_P, FOM, ρ_ar)
5. `core/calibration.py` — modelo de calibração
6. `firmware_arduino/firmware_arduino.ino` — interface com hardware
7. `app.py` — entrada principal e orquestração
8. Qualquer aba em `gui/` que seja relevante para a tarefa atual

---

<p align="center">
  <i>Última atualização: maio de 2026, antes da migração para Claude Code</i><br>
  <b>Céu Azul Aerodesign — UFSC</b>
</p>
