$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
node node_modules/typescript/bin/tsc
if ($LASTEXITCODE -ne 0) { throw 'TypeScript compilation failed' }
New-Item -ItemType Directory -Force dist/assets | Out-Null
& ./node_modules/@esbuild/win32-x64/esbuild.exe src/main.tsx --bundle --format=esm --minify --jsx=automatic --outfile=dist/assets/app.js '--define:import.meta.env={"PROD":true,"DEV":false,"MODE":"production"}' '--define:process.env.NODE_ENV="production"'
if ($LASTEXITCODE -ne 0) { throw 'JavaScript build failed' }
node node_modules/tailwindcss/lib/cli.js -i src/index.css -o dist/assets/app.css --minify
if ($LASTEXITCODE -ne 0) { throw 'CSS build failed' }
Copy-Item -Path public/* -Destination dist -Recurse -Force
Copy-Item -LiteralPath index.local.html -Destination dist/index.html -Force
