# Empacotamento e distribuicao do POLARIS

Este documento descreve como gerar o **executavel standalone** do POLARIS
(um `.exe` que roda em PCs sem Python) e o **instalador** (`setup.exe`),
e como o **auto-update** funciona.

## Visao geral da arquitetura

O POLARIS empacotado usa a estrategia **"runtime pesado + codigo leve"**:

```
POLARIS.exe  (PyInstaller: Python + matplotlib/pandas/numpy/... + launcher)
    │  ao abrir:
    ├─ 1. 1a vez: copia o codigo embarcado para %LOCALAPPDATA%\POLARIS\app
    ├─ 2. consulta o ultimo Release no GitHub
    ├─ 3. se a tag for mais nova, baixa so o zip do codigo (KB) e troca
    └─ 4. roda o app.py atualizado usando o Python de dentro do .exe
```

- **Codigo** fica em `%LOCALAPPDATA%\POLARIS\app` (substituido a cada update).
- **Dados do usuario** (config_local, ensaios, relatorios) ficam em
  `%LOCALAPPDATA%\POLARIS\` — **nunca** sao apagados por um update.
- O download pesado (~200 MB) so acontece na **primeira instalacao** e
  quando voce mudar as **bibliotecas** (ai gere um instalador novo).

## Pre-requisitos (maquina de build, so do desenvolvedor)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install pyserial numpy matplotlib pandas reportlab
pip install pyinstaller
```

Para o instalador: baixar o **Inno Setup** (https://jrsoftware.org/isdl.php).

## Gerar o executavel

Na raiz do repositorio, com o venv ativo:

```powershell
pyinstaller polaris.spec
```

Saida: `dist\POLARIS\POLARIS.exe` (pasta one-folder, ja distribuivel).

Teste rodando `dist\POLARIS\POLARIS.exe`. Se aparecer
`ModuleNotFoundError` de alguma lib, acrescente o nome em
`hiddenimports` no `polaris.spec` e rebuilde.

## Gerar o instalador (setup.exe)

1. Confirme que `MyAppVersion` em `installer\polaris.iss` == `__version__`
   em `version.py`.
2. Compile:

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\polaris.iss
```

Saida: `installer\Output\POLARIS-setup-<versao>.exe` — atalho no Menu
Iniciar, atalho opcional na area de trabalho e desinstalador.

## Publicar uma ATUALIZACAO (fluxo normal, sem rebuild)

Enquanto voce **nao** adiciona bibliotecas novas, atualizar e leve:

1. Faca suas mudancas no codigo e commit/push normal.
2. Suba a versao em `version.py` (ex: `1.0.0` -> `1.1.0`).
3. Crie um **Release** no GitHub com a tag **igual** (ex: `v1.1.0`):

   ```powershell
   git tag v1.1.0
   git push origin v1.1.0
   gh release create v1.1.0 --title "v1.1.0" --notes "Descricao das mudancas"
   ```

4. Pronto. Na proxima vez que qualquer POLARIS instalado abrir, ele
   detecta o Release novo, baixa so o codigo e se atualiza.

> O auto-update reage a **Releases**, nao a cada push na `main`. Assim a
> bancada nunca pega codigo pela metade durante o desenvolvimento.

## Quando REBUILD e obrigatorio (novo setup.exe)

- Adicionou/atualizou uma **biblioteca** (o runtime embarcado nao a tem).
- Mudou algo no `launcher.py`, `polaris.spec` ou no proprio empacotamento.

Nesses casos: rebuild (`pyinstaller polaris.spec`), gere o instalador novo
e distribua o `setup.exe`. (Uma futura melhoria: o updater checar uma
"versao minima de runtime" e avisar o usuario para baixar o novo setup.)

## Icone (opcional)

Coloque um `installer\polaris.ico` para o `.exe` e o instalador usarem.
Sem ele, o build usa o icone padrao.

## Modo desenvolvimento (inalterado)

Rodar do repositorio continua igual: `python app.py`. Nesse modo os dados
ficam no proprio repo (nao em LOCALAPPDATA) e nao ha auto-update.
