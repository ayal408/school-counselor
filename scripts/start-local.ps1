param([string]$CertificatePath, [switch]$LocalTranscription)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path '.env')) { throw 'Create .env from .env.example and configure its keys first.' }
New-Item -ItemType Directory -Path '.local' -Force | Out-Null
$destination = Join-Path (Get-Location) '.local/local-ca.pem'
if ($CertificatePath) {
    $source = (Resolve-Path $CertificatePath).Path
    $content = [IO.File]::ReadAllText($source)
    if ($content -match '-----BEGIN CERTIFICATE-----') {
        if ($content -match 'PRIVATE KEY') { throw 'Provide a public CA certificate, not a private key.' }
        [IO.File]::WriteAllText($destination, $content, [Text.Encoding]::ASCII)
    } else {
        $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 -ArgumentList $source
        $pem = "-----BEGIN CERTIFICATE-----`n" + [Convert]::ToBase64String($cert.RawData, [Base64FormattingOptions]::InsertLineBreaks) + "`n-----END CERTIFICATE-----`n"
        [IO.File]::WriteAllText($destination, $pem, [Text.Encoding]::ASCII)
    }
} else {
    # Export only already trusted NetFree roots, never the entire root store.
    $certs = @(Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root | Where-Object { ($_.Subject -match 'NetFree' -or $_.Issuer -match 'NetFree') } | Sort-Object Thumbprint -Unique)
    if ($certs.Count -eq 0) { throw 'No trusted NetFree root was found. Run with -CertificatePath pointing to the CA certificate supplied by your network administrator.' }
    $pem = ($certs | ForEach-Object {
        "-----BEGIN CERTIFICATE-----`n" + [Convert]::ToBase64String($_.RawData, [Base64FormattingOptions]::InsertLineBreaks) + "`n-----END CERTIFICATE-----`n"
    }) -join "`n"
    Write-Host ("Using {0} trusted NetFree root certificates." -f $certs.Count)
    [IO.File]::WriteAllText($destination, $pem, [Text.Encoding]::ASCII)
}
$env:LOCAL_CA_FILE = $destination
Write-Host 'Building with the supplied local CA. TLS verification remains enabled.'
$composeArgs = @('-f', 'docker-compose.yml', '-f', 'compose.local-ca.yml')
if ($LocalTranscription) {
    if (-not (Test-Path 'models/whisper/model.bin')) { throw 'Download the local model first. See docs/casework.md.' }
    $composeArgs += @('-f', 'compose.local-transcription.yml', '-f', 'compose.local-transcription-ca.yml')
}
docker compose @composeArgs up --build -d
if ($LASTEXITCODE -ne 0) { throw 'Docker build/start failed. Check the preceding error.' }
Write-Host 'App: http://localhost:8088'
Write-Host 'Create the first user: docker compose exec counselor-server python -m app.create_user'
