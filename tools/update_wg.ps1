<#
update_wg.ps1 —— WoWs 大版本更新的 PC 侧一键脚本。

流程:认 build → 校验区服 → 判断要不要干活 → 提数据 → **硬性校验产物** →
上传到服务器暂存区 → 写完成标记 → 提示去 QQ 发 /更新wg版本。

为什么不是「少敲几条命令」:
  1. `wows-data-mgr dump-renderer-data` 遇到未知实体类型时**不会失败** —— 静默跳过
     GameParams 重新派生、只打一行 WARN、仍然 exit 0。产出目录缺 game_params.rkyv,
     船只数据全无。15.7 那次就是这么中招的。所以第 5 步用 dumpcheck.py 硬查,
     **不通过就绝不上传**。
  2. 客户端可能是公开测试服或国服(build 体系独立),从它提数据只会污染服务器数据集 ——
     第 2 步硬拒绝。
  3. scp 传一半断了而目录已经落在生产路径里,渲染器会挑中那个半截目录然后诡异报错 ——
     所以传到**暂存区** incoming/,并在传完后写一个**同级**的 <ver>_<build>.done 标记;
     没有标记,服务器侧指令不会碰那个目录。

参数:
  -DryRun     跑到第 5 步(校验)为止,不上传。用于验证脚本本身。
  -AllowWarn  只放过日志里的 WARN 这一档判据(panic / 未知实体类型 / 缺文件不可跳过)。
              用了会记进完成标记,服务器侧汇报会带出来 —— 免得悄悄放过。

配置全部可用环境变量覆盖,见下面的「配置」一段。
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$AllowWarn
)

# 不设 $ErrorActionPreference='Stop':提数据的二进制会往 stderr 打正常日志,
# Stop 模式下 PowerShell 会把它当致命错误抛出。这里改成每一步显式查退出码。
$ErrorActionPreference = 'Continue'

# 往 ssh 的 stdin 里灌完成标记时用 UTF-8(PS 5.1 默认是 ASCII)。
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)

# ---------------------------------------------------------------- 小工具

function Step([string]$msg) {
    Write-Host ''
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Note([string]$msg) { Write-Host "    $msg" }

function Good([string]$msg) { Write-Host "    $msg" -ForegroundColor Green }

function Die([string]$msg) {
    Write-Host ''
    Write-Host "[停止] $msg" -ForegroundColor Red
    exit 1
}

function EnvOr([string]$name, [string]$fallback) {
    $v = [Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrWhiteSpace($v)) { return $fallback }
    return $v.Trim()
}

# ---------------------------------------------------------------- 配置

$GameDir      = EnvOr 'WOWS_GAME_DIR'      'C:\Program Files (x86)\Steam\steamapps\common\World of Warships'
$DataMgr      = EnvOr 'WOWS_DATA_MGR'      'C:\Users\29801\Desktop\minimap\wows-toolkit\target\release\wows-data-mgr.exe'
$ExtractedOut = EnvOr 'WOWS_EXTRACTED_OUT' 'C:\Users\29801\Desktop\minimap\wows-toolkit\extracted'
$SshTarget    = EnvOr 'WOWS_SSH_TARGET'    'zifeng@192.168.31.252'
$IncomingRoot = (EnvOr 'WOWS_INCOMING'     '/var/lib/wows-data/incoming').TrimEnd('/')
$PythonExe    = EnvOr 'WOWS_PYTHON'        'python'

# 区服要求**不给环境变量覆盖**:这道闸的全部意义就是「手滑用测试服客户端提数据」时拦住,
# 留个后门等于没有这道闸。真要从别的服提数据,那是另一条流程,不走这个脚本。
$RequiredRealm = 'asia'

$RepoRoot        = Split-Path -Parent $PSScriptRoot
$DumpCheck       = Join-Path $RepoRoot 'report\lib\wowsbot\dumpcheck.py'
$WowsbotLibDir   = Join-Path $RepoRoot 'report\lib'
# 服务器上的生产目录是 incoming/ 的同级 extracted/
$ServerExtracted = ($IncomingRoot -replace '/[^/]+$', '') + '/extracted'

Write-Host '=============================================================='
Write-Host ' WoWs 大版本更新 —— PC 侧(提数据 → 校验 → 传到服务器暂存区)'
Write-Host '=============================================================='
Write-Host "游戏目录     : $GameDir"
Write-Host "提数据二进制 : $DataMgr"
Write-Host "输出目录     : $ExtractedOut"
Write-Host "服务器       : $SshTarget"
Write-Host "暂存区       : $IncomingRoot"
Write-Host "生产目录     : $ServerExtracted"
Write-Host "校验脚本     : $DumpCheck"
Write-Host "python       : $PythonExe"
Write-Host "-DryRun      : $DryRun    -AllowWarn : $AllowWarn"

# ---------------------------------------------------------------- 前置检查

Step '0/7 前置检查'
if (-not (Test-Path -LiteralPath $GameDir -PathType Container)) {
    Die "游戏目录不存在:$GameDir(用环境变量 WOWS_GAME_DIR 指到正确位置)"
}
if (-not (Test-Path -LiteralPath $DumpCheck -PathType Leaf)) {
    Die "找不到校验脚本 $DumpCheck —— 这个脚本必须放在仓库的 tools\ 下才能找到 report\lib"
}
if (-not (Get-Command $PythonExe -ErrorAction SilentlyContinue)) {
    Die "找不到 python($PythonExe)。校验这一步离不开它,拒绝继续(用 WOWS_PYTHON 指定)"
}
if (-not (Test-Path -LiteralPath $DataMgr -PathType Leaf)) {
    Die "找不到提数据的二进制:$DataMgr(先在 wows-toolkit 里 cargo build --release,或用 WOWS_DATA_MGR 指定)"
}
Good '游戏目录、dumpcheck.py、python、wows-data-mgr 都在'

# ---------------------------------------------------------------- 1 认 build

Step '1/7 认 build(游戏目录 bin\ 下最大的纯数字目录)'
$binDir = Join-Path $GameDir 'bin'
if (-not (Test-Path -LiteralPath $binDir -PathType Container)) {
    Die "游戏目录下没有 bin\:$binDir —— 这看着不像一个 WoWs 安装目录"
}
$buildDir = Get-ChildItem -LiteralPath $binDir -Directory |
    Where-Object { $_.Name -match '^\d+$' } |
    Sort-Object { [long]$_.Name } |
    Select-Object -Last 1
if (-not $buildDir) {
    Die "bin\ 下一个以 build 号命名的目录都没有:$binDir"
}
$build = [long]$buildDir.Name
Good "build = $build"

# ---------------------------------------------------------------- 2 校验区服

Step '2/7 校验区服(currentrealm.txt 必须是 asia)'
$realmFile = Join-Path $GameDir 'currentrealm.txt'
if (-not (Test-Path -LiteralPath $realmFile -PathType Leaf)) {
    Die "找不到 $realmFile —— 无法确认这个客户端是哪个服的。宁可不传也不能传脏数据,已停止"
}
$realm = (Get-Content -LiteralPath $realmFile -Raw).Trim()
if ($realm -ne $RequiredRealm) {
    Die @"
当前客户端是 $realm 服,不是 $RequiredRealm。从公开测试服/国服提数据会污染数据集
(各服 build 体系独立,build 号对不上,渲染器会挑错版本),已停止。
如果你刚在 WGC 里切过服,把客户端切回亚服跑一遍完整更新再来。
"@
}
Good "区服 = $realm"

# ---------------------------------------------------------------- 3 判断要不要干活

Step '3/7 判断要不要干活(本机已提取 + 服务器已有 = 游戏还没更新)'
$localVerDir = $null
if (Test-Path -LiteralPath $ExtractedOut -PathType Container) {
    $hit = @(Get-ChildItem -LiteralPath $ExtractedOut -Directory |
        Where-Object { $_.Name -match "_$build$" })
    if ($hit.Count -gt 0) { $localVerDir = $hit[0].FullName }
}
if ($localVerDir) { Note "本机已有:$localVerDir" }
else { Note "本机 $ExtractedOut 下没有 build $build 的数据" }

$sshProbe = & ssh -o BatchMode=yes -o ConnectTimeout=10 $SshTarget "ls -d $ServerExtracted/*_$build" 2>&1
$sshCode = $LASTEXITCODE
if ($sshCode -eq 255) {
    Die @"
ssh 连不上 $SshTarget(退出码 255):
  $($sshProbe -join "`n  ")
连不上就既没法确认服务器是不是已经有这个 build,也没法上传 —— 与其提完 294MB 再卡住,
不如现在停。检查网络 / 服务器是否开机后重试。
"@
}
$serverHas = ($sshCode -eq 0)
if ($serverHas) { Note "服务器已有:$($sshProbe | Select-Object -First 1)" }
else { Note "服务器 $ServerExtracted 下没有 build $build 的数据" }

if ($localVerDir -and $serverHas) {
    Write-Host ''
    Write-Host "游戏还没更新(当前 build $build 已是最新:本机已提取、服务器也已有)。什么都不用做。" -ForegroundColor Green
    exit 0
}
if ($localVerDir -and -not $serverHas) {
    Note '本机有、服务器没有 —— 会重新提一遍(保证产物完整、日志可校验)再上传。'
}

# ---------------------------------------------------------------- 4 提数据

Step "4/7 提数据(dump-renderer-data,约 294MB,要几分钟)"
# 日志写进 $ExtractedOut 里面,不要写到它的上一级 —— 上一级是 wows-toolkit 仓库根,
# 而 extracted/ 本身是被 git 忽略的,所以放里面不会每次更新都多一个 untracked 文件。
$LogPath = Join-Path $ExtractedOut "dump-$build.log"
Note "日志:$LogPath"
if (-not (Test-Path -LiteralPath $ExtractedOut -PathType Container)) {
    New-Item -ItemType Directory -Path $ExtractedOut -Force | Out-Null
}

# 不用 Tee-Object:PS 5.1 的 Tee-Object -FilePath 写出来是 UTF-16,而 dumpcheck.py
# 按 UTF-8 读日志 —— 那样日志里的 WARN / panic 一条都匹配不上,校验会**假过**。
# 这里自己收行,最后用无 BOM 的 UTF-8 落盘。
$dumpLines = New-Object System.Collections.Generic.List[string]
& $DataMgr dump-renderer-data --game-dir $GameDir --build $build -o $ExtractedOut 2>&1 |
    ForEach-Object {
        $line = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { [string]$_ }
        Write-Host $line
        $dumpLines.Add($line)
    }
$dumpExit = $LASTEXITCODE
[IO.File]::WriteAllLines($LogPath, $dumpLines, (New-Object System.Text.UTF8Encoding($false)))
if ($dumpExit -ne 0) {
    Die "wows-data-mgr 退出码 $dumpExit —— 提数据失败,日志在 $LogPath。没有上传任何东西。"
}
Good "提数据结束(exit 0),日志 $($dumpLines.Count) 行 —— 但 exit 0 不代表数据是对的,接着校验"

$hit = @(Get-ChildItem -LiteralPath $ExtractedOut -Directory |
    Where-Object { $_.Name -match "_$build$" })
if ($hit.Count -eq 0) {
    Die "提完之后 $ExtractedOut 下还是没有 *_$build 目录 —— 产物根本没落盘,日志在 $LogPath"
}
if ($hit.Count -gt 1) {
    Die "$ExtractedOut 下有多个 *_$build 目录($($hit.Name -join ', ')) —— 不知道该传哪个,先手动清理"
}
$verDir  = $hit[0].FullName
$verName = $hit[0].Name
Good "产物目录:$verDir"

# ---------------------------------------------------------------- 5 校验产物

Step '5/7 校验产物(dumpcheck.py:关键路径 + rkyv 大小 + 日志关键字)'
$checkArgs = @($DumpCheck, $verDir, '--log', $LogPath)
if ($AllowWarn) { $checkArgs += '--allow-warn' }
& $PythonExe @checkArgs
$checkExit = $LASTEXITCODE
if ($checkExit -eq 2) {
    Die "dumpcheck.py 用法错(退出码 2)—— 脚本传参有问题,没有上传任何东西。"
}
if ($checkExit -ne 0) {
    Die @"
产物校验未通过(上面逐条列出原因)。**没有上传任何东西** —— 这是故意的:
传上去之后服务器侧虽然还有一道复校验,但那时 294MB 已经白传了,而且人会以为
「传上去了应该就没事」。

怎么办:
  - 日志里是 `Unrecognized type <X>`:WG 加了新实体类型。不要动数据,
    按 docs\REPLAYSHARK_BUILD.md §8 给 parse_type 加分支、重编 wows-data-mgr 再跑。
  - 缺 game_params.rkyv / rkyv 偏小:GameParams 重新派生被静默跳过了,同上,先修二进制。
  - 只是一条无害的 WARN:把原文看清楚,确认无害后加 -AllowWarn 重跑
    (只放过 WARN 这一档;panic / 未知类型 / 缺文件加了也照样拦)。
完整日志:$LogPath
"@
}
Good '校验通过'

if ($DryRun) {
    Write-Host ''
    Write-Host "dry-run:校验通过,未上传。产物 $verDir" -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------- 6 上传到暂存区

Step "6/7 上传到暂存区 $IncomingRoot"
# 先把可能存在的旧标记删掉:万一这次传一半断了,残留的旧标记会让服务器侧
# 把半截目录当成「传完了」。标记必须是这次传完之后才写的。
$prep = "mkdir -p '$IncomingRoot' && rm -f '$IncomingRoot/$verName.done'"
& ssh -o BatchMode=yes $SshTarget $prep
if ($LASTEXITCODE -ne 0) {
    Die "在服务器上准备暂存区失败(ssh 退出码 $LASTEXITCODE):$prep"
}
Note "scp -r $verDir -> ${SshTarget}:$IncomingRoot/"
& scp -r $verDir "${SshTarget}:$IncomingRoot/"
if ($LASTEXITCODE -ne 0) {
    Die @"
scp 失败(退出码 $LASTEXITCODE)。暂存区里可能留着一个半截目录,但**没有写完成标记**,
所以服务器侧不会碰它 —— 直接重跑本脚本即可(scp 会续着传)。
"@
}
Good '传完了'

# ---------------------------------------------------------------- 7 写完成标记

Step "7/7 写完成标记 $IncomingRoot/$verName.done"
$sumJson = & $PythonExe -c "import json,sys; sys.path.insert(0, sys.argv[1]); from wowsbot import dumpcheck; print(json.dumps(dumpcheck.summarize(sys.argv[2])))" $WowsbotLibDir $verDir
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($sumJson)) {
    Die "取产物摘要失败(dumpcheck.summarize)。数据已经在 $IncomingRoot/$verName,但没有标记,服务器侧不会动它。"
}
$sum = $sumJson | ConvertFrom-Json
# 标记内容保持纯 ASCII:它要通过 ssh 的 stdin 灌到服务器上,别在编码上找麻烦。
$who = "$env:COMPUTERNAME/$env:USERNAME" -replace '[^\x20-\x7E]', '?'
$marker = [ordered]@{
    version     = $sum.version
    version_str = $sum.version_str
    build       = $sum.build
    sizes       = $sum.sizes
    realm       = $realm
    allow_warn  = [bool]$AllowWarn
    uploaded_at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
    uploaded_by = $who
} | ConvertTo-Json -Depth 5

# 标记是**与版本目录同级的文件**,不放在目录里面 —— 否则服务器侧 mv 会把它一起
# 搬进 extracted/,在生产目录里留个没用的文件。
$marker | & ssh -o BatchMode=yes $SshTarget "cat > '$IncomingRoot/$verName.done'"
if ($LASTEXITCODE -ne 0) {
    Die "写完成标记失败(ssh 退出码 $LASTEXITCODE)。数据在 $IncomingRoot/$verName,但没有标记,服务器侧不会动它 —— 重跑本脚本。"
}
Good "标记已写:$IncomingRoot/$verName.done"
if ($AllowWarn) {
    Write-Host '    注意:这次用了 -AllowWarn,标记里记了一笔,服务器侧汇报会带出来。' -ForegroundColor Yellow
}

Write-Host ''
Write-Host "完成:$verName 已在服务器暂存区,标记已写。" -ForegroundColor Green
Write-Host '下一步:去 QQ 发 /更新wg版本' -ForegroundColor Green
exit 0
