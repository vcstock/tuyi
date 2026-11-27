param([switch]$ExpectGpu)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$build = Join-Path $root 'build'
$dist = Join-Path $root 'dist'
$runtime = Join-Path $build 'codex'
$stage = Join-Path $runtime 'stage'
$codexVersion = '0.172.0'
$python = Join-Path $root '.venv\Scripts\python.exe'

function Assert-Exit {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE)." }
}

New-Item -ItemType Directory -Force $build, $runtime, $stage | Out-Null
if (!(Test-Path $python)) {
    py -3.11 -m venv (Join-Path $root '.venv')
    Assert-Exit 'Creating Python environment'
}
& $python -m pip install -r (Join-Path $root 'requirements-windows.txt')
Assert-Exit 'Installing Windows dependencies'
& $python -m pip install --no-deps rapidocr-onnxruntime==1.3.8
Assert-Exit 'Installing RapidOCR'

$package = Join-Path $runtime "openai-codex-$codexVersion-win32-x64.tgz"
if (!(Test-Path $package)) {
    npm.cmd pack "@openai/codex@$codexVersion-win32-x64" --pack-destination $runtime --registry https://registry.npmjs.org
    Assert-Exit 'Downloading Codex CLI'
}
tar.exe -xf $package -C $runtime
Assert-Exit 'Unpacking Codex CLI'
$vendor = Join-Path $runtime 'package\vendor\x86_64-pc-windows-msvc'
New-Item -ItemType Directory -Force "$stage\bin", "$stage\codex-path", "$stage\codex-resources" | Out-Null
Copy-Item "$vendor\bin\*.exe" "$stage\bin" -Force
Copy-Item "$vendor\codex-path\rg.exe" "$stage\codex-path" -Force
Copy-Item "$vendor\codex-resources\*.exe" "$stage\codex-resources" -Force
Copy-Item "$vendor\codex-package.json" $stage -Force
Invoke-WebRequest "https://raw.githubusercontent.com/openai/codex/rust-v$codexVersion/LICENSE" -OutFile "$stage\LICENSE"

Push-Location $root
try {
    $arguments = @(
        '--noconfirm', '--onefile', '--windowed', '--name', 'TuYi', '--exclude-module', 'sympy',
        '--collect-data', 'rapidocr_onnxruntime', '--copy-metadata', 'rapidocr-onnxruntime',
        '--collect-binaries', 'onnxruntime', '--copy-metadata', 'onnxruntime-directml',
        '--add-data', "$stage;codex-runtime", '--distpath', $dist,
        '--workpath', "$build\pyinstaller", '--specpath', $build, 'app.py'
    )
    & $python -m PyInstaller @arguments
    Assert-Exit 'Building TuYi.exe'
    if ($ExpectGpu) { $env:TUYI_SMOKE_EXPECT_GPU = '1' }
    $output = Join-Path $dist 'TuYi.exe'
    $smoke = Join-Path $build 'smoke.png'
    $run = Start-Process $output -ArgumentList ('--smoke-test "{0}"' -f $smoke) -WindowStyle Hidden -Wait -PassThru
    if ($run.ExitCode -ne 0) { throw "TuYi.exe smoke test failed (exit $($run.ExitCode))." }
    Get-FileHash $output -Algorithm SHA256
} finally {
    if ($ExpectGpu) { Remove-Item Env:TUYI_SMOKE_EXPECT_GPU -ErrorAction SilentlyContinue }
    Pop-Location
}
