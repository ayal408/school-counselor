param([string]$CertificatePath)
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
    # Export only an already trusted NetFree root, never the entire root store.
    $certs = @(Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root | Where-Object { $_.Subject -match 'NetFree' } | Sort-Object Thumbprint -Unique)
    if ($certs.Count -ne 1) { throw 'A single trusted NetFree root was not found. Run with -CertificatePath pointing to the CA certificate supplied by your network administrator.' }
    $pem = "-----BEGIN CERTIFICATE-----`n" + [Convert]::ToBase64String($certs[0].RawData, [Base64FormattingOptions]::InsertLineBreaks) + "`n-----END CERTIFICATE-----`n"
    [IO.File]::WriteAllText($destination, $pem, [Text.Encoding]::ASCII)
}
$env:LOCAL_CA_FILE = $destination
Write-Host 'Building with the supplied local CA. TLS verification remains enabled.'
docker compose -f docker-compose.yml -f compose.local-ca.yml up --build -d
if ($LASTEXITCODE -ne 0) { throw 'Docker build/start failed. Check the preceding error.' }
Write-Host 'App: http://localhost:8088'
Write-Host 'Create the first user: docker compose exec counselor-server python -m app.create_user'
