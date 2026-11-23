<#
.SYNOPSIS
  Install the ABAP documentation skills into Claude Code by copying them.

.DESCRIPTION
  Copies every folder under skills\ into your personal skills folder
  (%USERPROFILE%\.claude\skills) or, with -Project, into .\.claude\skills of
  the current directory. An existing copy is moved to
  %USERPROFILE%\.claude\skills-backup\<name>-<timestamp> first; backups are
  kept outside the skills folder so Claude Code does not load them as
  duplicate skills.

  Prefer the plugin install (see README) if you want updates via /plugin.

.EXAMPLE
  .\tools\install.ps1
  .\tools\install.ps1 -Project
#>
param([switch]$Project)

$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '..\skills' | Resolve-Path
$target = if ($Project) { Join-Path (Get-Location) '.claude\skills' } else { Join-Path $HOME '.claude\skills' }
$backupRoot = Join-Path $HOME '.claude\skills-backup'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

New-Item -ItemType Directory -Force $target | Out-Null

Get-ChildItem $source -Directory | ForEach-Object {
    $dest = Join-Path $target $_.Name
    if (Test-Path $dest) {
        New-Item -ItemType Directory -Force $backupRoot | Out-Null
        $backup = Join-Path $backupRoot "$($_.Name)-$stamp"
        Move-Item $dest $backup
        Write-Host "  backed up existing $($_.Name) -> $backup"
    }
    Copy-Item $_.FullName $dest -Recurse -Exclude '__pycache__', '*.pyc'
    Write-Host "  installed $($_.Name) -> $dest"
}

Write-Host "`nDone. Restart Claude Code (or start a new session) to pick up the skills."
