param(
    [string]$RemoteUrl = "https://github.com/xtreme00zzz/car_inspection.git",
    [string]$Branch = "main",
    [string]$CommitMessage = "Initial commit",
    [string]$GitHubToken,
    [bool]$Private = $false
)

$ErrorActionPreference = 'Stop'

function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Test-GitInstalled {
    try {
        git --version | Out-Null
        return $true
    } catch { return $false }
}

function Ensure-Git {
    if (Test-GitInstalled) { return }
    Write-Warn "Git not found. Attempting install via winget."
    try {
        winget --version | Out-Null
    } catch {
        throw "winget is not available. Please install Git manually from https://git-scm.com/download/win and rerun."
    }
    Write-Info "Installing Git (this may prompt for consent)..."
    winget install --id Git.Git -e --source winget
    if (-not (Test-GitInstalled)) {
        throw "Git installation did not complete. Install Git and retry."
    }
}

function Ensure-GitIdentity {
    $name = (git config user.name) 2>$null
    $email = (git config user.email) 2>$null
    if (-not $name) {
        $name = Read-Host "Enter your Git user.name"
        git config user.name "$name"
    }
    if (-not $email) {
        $email = Read-Host "Enter your Git user.email"
        git config user.email "$email"
    }
}

function Ensure-Branch($branch) {
    $current = (git rev-parse --abbrev-ref HEAD) 2>$null
    if (-not $current -or $current -eq 'HEAD') {
        Write-Info "Creating branch '$branch'"
        git checkout -b "$branch"
    } elseif ($current -ne $branch) {
        Write-Info "Renaming branch '$current' to '$branch'"
        git branch -M "$branch"
    }
}

function Ensure-Remote($url) {
    try {
        $existing = git remote get-url origin 2>$null
        if ($existing) {
            if ($existing -ne $url) {
                Write-Info "Updating remote 'origin' to $url"
                git remote set-url origin "$url"
            } else {
                Write-Info "Remote 'origin' already set to $url"
            }
        } else {
            throw "No origin"
        }
    } catch {
        Write-Info "Adding remote 'origin' => $url"
        git remote add origin "$url"
    }
}

function Parse-GitHubRemote($url) {
    # Supports https and ssh
    # https://github.com/owner/repo.git
    # git@github.com:owner/repo.git
    $owner = $null; $repo = $null
    if ($url -match 'github\.com[:/]+([^/]+)/([^\.]+)') {
        $owner = $Matches[1]
        $repo = $Matches[2]
    }
    return @{ owner = $owner; repo = $repo }
}

function Ensure-GitHubRepo($url, $token, $isPrivate) {
    if (-not $token) { return }
    $parsed = Parse-GitHubRemote $url
    if (-not $parsed.owner -or -not $parsed.repo) { return }
    $owner = $parsed.owner
    $repo  = $parsed.repo

    $headers = @{ 
        'Authorization' = "Bearer $token";
        'Accept'        = 'application/vnd.github+json';
        'User-Agent'    = 'publish-script'
    }
    $repoUrl = "https://api.github.com/repos/$owner/$repo"
    try {
        Invoke-RestMethod -Method GET -Uri $repoUrl -Headers $headers | Out-Null
        Write-Info "GitHub repo '$owner/$repo' already exists."
        return
    } catch {
        # 404 -> create
        Write-Info "Creating GitHub repo '$owner/$repo'"
        $body = @{ name = $repo; private = $isPrivate }
        # Note: This creates under the authenticated user. If $owner differs, user must have permissions.
        Invoke-RestMethod -Method POST -Uri "https://api.github.com/user/repos" -Headers $headers -Body ($body | ConvertTo-Json) | Out-Null
        Write-Info "Created GitHub repo '$owner/$repo'"
    }
}

function Commit-IfNeeded($message) {
    $status = git status --porcelain
    if ($status) {
        Write-Info "Committing changes"
        git commit -m "$message"
    } else {
        Write-Info "Nothing to commit (working tree clean)"
    }
}

function Try-Push($branch) {
    try {
        git push -u origin "$branch"
        return $true
    } catch {
        Write-Warn "Push failed. Attempting to merge remote '$branch' (unrelated histories)."
        try {
            git fetch origin
            git merge --allow-unrelated-histories -m "Merge remote '$branch'" "origin/$branch"
            git push -u origin "$branch"
            return $true
        } catch {
            Write-Err "Push still failed. Please check your credentials and remote permissions."
            return $false
        }
    }
}

# Main
try {
    # Move to repo root (parent of scripts folder)
    $repoRoot = Split-Path $PSScriptRoot -Parent
    Set-Location $repoRoot

    Ensure-Git
    Write-Info "Using repo at: $repoRoot"

    if (-not (Test-Path .git)) {
        Write-Info "Initializing new Git repository"
        git init | Out-Null
    } else {
        Write-Info "Existing Git repository detected"
    }

    Ensure-Branch -branch $Branch
    git add -A
    Ensure-GitIdentity
    Commit-IfNeeded -message $CommitMessage
    Ensure-Remote -url $RemoteUrl

    # Try creating GitHub repo if it doesn't exist and token was provided
    Ensure-GitHubRepo -url $RemoteUrl -token $GitHubToken -isPrivate $Private

    if (Try-Push -branch $Branch) {
        Write-Host "Successfully pushed to $RemoteUrl ($Branch)" -ForegroundColor Green
        exit 0
    } else {
        exit 1
    }
} catch {
    Write-Err $_
    exit 1
}
