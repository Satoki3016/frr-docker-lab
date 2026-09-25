# =============================================================================
# RADWIN TerraNet 無線チェーン検証スクリプト（Windows / PowerShell 版）
#
# 用途:
#   Windows ノートPC を KeepLINK-A (ODU-A 側) の空きポートに挿した状態で実行し、
#   60GHz 無線2ホップの疎通・RTT・通過MTU・スループットを確認する。
#   SONiC には一切触れないため、既存の実験環境を壊す心配なく実行できる。
#
# 検証対象のチェーン:
#   [PC]-KeepLINK-A-[.31] )))無線1((( [.32]-中継-[.33] )))無線2((( [.34]-KeepLINK-C
#
# 使い方（PowerShell を「管理者として実行」）:
#   .\scripts\radwin_verify.ps1                        … アダプタ一覧を表示
#   .\scripts\radwin_verify.ps1 -Adapter "イーサネット"
#   .\scripts\radwin_verify.ps1 -Adapter "イーサネット" -Peer 192.168.1.200
#
#   実行がブロックされる場合は次を先に実行:
#     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
# =============================================================================

param(
    [string]$Adapter = "",
    [string]$Peer    = "",
    [string]$MyIP    = "192.168.1.100",
    [int]   $Prefix  = 24
)

$ErrorActionPreference = "Continue"

# チェーン上の ODU。手前から奥への順。
$OduIp = @("192.168.1.31","192.168.1.32","192.168.1.33","192.168.1.34")
$OduDesc = @(
    "ODU-A  有線直結（KeepLINK-A 経由・必ず通るはず）",
    "ODU-B  無線1 を越える",
    "ODU-C  無線1 + 中継 を越える",
    "ODU-D  無線1 + 中継 + 無線2 を越える"
)
$OduCause = @(
    "KeepLINK-A の配線、PC の IP 設定、または ODU-A の電源",
    "無線1 (ODU-A .31 <-> ODU-B .32) が未確立",
    "中継セグメント (ODU-B .32 <-> ODU-C .33) の有線配線",
    "無線2 (ODU-C .33 <-> ODU-D .34) が未確立"
)

function Write-Hr { Write-Host "-------------------------------------------------------------" }

# .NET の Ping を使う。ping.exe の出力は OS の言語で変わるため解析に使わない。
$Pinger = New-Object System.Net.NetworkInformation.Ping

function Test-Ping {
    param([string]$Target, [int]$Count = 5, [int]$Timeout = 2000)
    $ok = 0; $sum = 0
    for ($i = 0; $i -lt $Count; $i++) {
        try {
            $r = $Pinger.Send($Target, $Timeout)
            if ($r.Status -eq "Success") { $ok++; $sum += $r.RoundtripTime }
        } catch { }
        Start-Sleep -Milliseconds 150
    }
    $avg = if ($ok -gt 0) { [math]::Round($sum / $ok, 2) } else { $null }
    return [pscustomobject]@{ Sent = $Count; Received = $ok; AvgRtt = $avg }
}

function Test-Mtu {
    param([string]$Target, [int]$Mtu, [int]$Timeout = 2000)
    # ping のペイロード長 = MTU - 28 (IPヘッダ20 + ICMPヘッダ8)
    $size = $Mtu - 28
    if ($size -lt 0) { return $false }
    $buf  = [byte[]]::new($size)
    $opt  = New-Object System.Net.NetworkInformation.PingOptions
    $opt.DontFragment = $true
    for ($i = 0; $i -lt 2; $i++) {
        try {
            $r = $Pinger.Send($Target, $Timeout, $buf, $opt)
            if ($r.Status -eq "Success") { return $true }
        } catch { }
    }
    return $false
}

# -----------------------------------------------------------------------------
Write-Host "============================================================="
Write-Host " RADWIN 無線チェーン検証   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "============================================================="

# --- アダプタ未指定なら一覧を出して終了 -------------------------------------
if ([string]::IsNullOrWhiteSpace($Adapter)) {
    Write-Host ""
    Write-Host "アダプタ名を指定してください。有線 LAN のアダプタ一覧:"
    Write-Host ""
    Get-NetAdapter | Where-Object { $_.MediaType -ne "Native 802.11" } |
        Select-Object Name, InterfaceDescription, Status, LinkSpeed |
        Format-Table -AutoSize
    Write-Host "ケーブルが挿さっているものは Status が Up になります。"
    Write-Host ""
    Write-Host "例: .\scripts\radwin_verify.ps1 -Adapter `"イーサネット`""
    exit 1
}

$nic = Get-NetAdapter -Name $Adapter -ErrorAction SilentlyContinue
if ($null -eq $nic) {
    Write-Host "[NG] アダプタ '$Adapter' が見つかりません。"
    Write-Host "     引数なしで実行すると一覧が出ます。"
    exit 1
}
if ($nic.Status -ne "Up") {
    Write-Host "[警告] アダプタ '$Adapter' の Status が '$($nic.Status)' です。"
    Write-Host "       ケーブルが挿さっているか確認してください。"
}

# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "[0] PC 側の準備"
Write-Hr

$curId   = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal($curId)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "  [警告] 管理者権限がありません。IP の自動設定はスキップします。"
    Write-Host "         PowerShell を「管理者として実行」し直すか、"
    Write-Host "         手動で $MyIP / 255.255.255.0 を設定してください。"
} else {
    $existing = Get-NetIPAddress -InterfaceAlias $Adapter -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                Where-Object { $_.IPAddress -eq $MyIP }
    if ($existing) {
        Write-Host "  $MyIP は設定済み"
    } else {
        try {
            New-NetIPAddress -InterfaceAlias $Adapter -IPAddress $MyIP -PrefixLength $Prefix -ErrorAction Stop | Out-Null
            Write-Host "  $MyIP/$Prefix を '$Adapter' に追加した"
        } catch {
            Write-Host "  [警告] IP を追加できなかった: $($_.Exception.Message)"
        }
    }
    netsh interface ip delete arpcache | Out-Null
    Write-Host "  ARP キャッシュをクリアした"
}

Write-Host ""
Write-Host "  現在の '$Adapter' の IPv4:"
Get-NetIPAddress -InterfaceAlias $Adapter -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host "    $($_.IPAddress)/$($_.PrefixLength)" }

# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "[1] チェーン疎通確認（手前から順に ping）"
Write-Hr

# 60GHz の TDD はトラフィックが無いとスケジューリングが疎になり、最初のパケットが
# 待たされる。計測順序によって RTT が逆転するため、先に全ホップを温めておく。
Write-Host "  ウォームアップ中（無線のTDDスケジューリングを安定させる）..."
Test-Ping -Target $OduIp[$OduIp.Count-1] -Count 20 | Out-Null
Write-Host ""

$reached = -1
$rtt = @($null, $null, $null, $null)
for ($i = 0; $i -lt $OduIp.Count; $i++) {
    Write-Host ("  {0,-15} {1}" -f $OduIp[$i], $OduDesc[$i])
    Test-Ping -Target $OduIp[$i] -Count 3 | Out-Null   # 宛先ごとの助走（ARP解決含む）
    $r = Test-Ping -Target $OduIp[$i] -Count 20
    if ($r.Received -eq $r.Sent) {
        $rtt[$i] = $r.AvgRtt
        Write-Host ("      -> OK    平均RTT {0} ms" -f $r.AvgRtt)
        $reached = $i
    } elseif ($r.Received -gt 0) {
        $rtt[$i] = $r.AvgRtt
        $lost = $r.Sent - $r.Received
        Write-Host ("      -> 不安定  {0}/{1} 応答  平均RTT {2} ms（損失 {3}）" -f $r.Received, $r.Sent, $r.AvgRtt, $lost)
        $reached = $i
    } else {
        Write-Host "      -> NG    応答なし"
        break
    }
}

Write-Host ""
if ($reached -eq ($OduIp.Count - 1)) {
    Write-Host "  [OK] チェーン完成。無線2ホップとも疎通している。"
} else {
    $failed = $reached + 1
    Write-Host ("  [NG] {0} に到達できない。" -f $OduIp[$failed])
    Write-Host ("       想定原因: {0}" -f $OduCause[$failed])
    Write-Host ""
    Write-Host "  ここで停止する。原因を解消してから再実行すること。"
    exit 1
}

Write-Host ""
Write-Host "  ホップごとの RTT 増分:"
Write-Host "    （注: 各ODUの管理CPUの応答時間を含むため、伝搬遅延そのものではない。"
Write-Host "      負の値が出る場合は無線が十分に温まっていない。参考値として扱うこと）"
for ($i = 1; $i -lt $OduIp.Count; $i++) {
    if ($null -ne $rtt[$i] -and $null -ne $rtt[$i-1]) {
        $d = [math]::Round($rtt[$i] - $rtt[$i-1], 2)
        Write-Host ("    {0} -> {1} : {2} ms" -f $OduIp[$i-1], $OduIp[$i], $d)
    }
}

# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "[2] 通過 MTU の確認（ODU 設定上限は 7900、ラボ側は 9100）"
Write-Hr

$target = $OduIp[3]

# 送信元アダプタの MTU が小さいと経路ではなく PC 側で頭打ちになる。先に引き上げる。
$origMtu = (Get-NetIPInterface -InterfaceAlias $Adapter -AddressFamily IPv4 -ErrorAction SilentlyContinue).NlMtu
if ($null -eq $origMtu) { $origMtu = 1500 }
$mtuRaised = $false
if ($origMtu -lt 7900) {
    if ($isAdmin) {
        netsh interface ipv4 set subinterface "$Adapter" mtu=7900 store=active | Out-Null
        $now = (Get-NetIPInterface -InterfaceAlias $Adapter -AddressFamily IPv4 -ErrorAction SilentlyContinue).NlMtu
        if ($now -ge 7900) {
            $mtuRaised = $true
            Write-Host "  送信元アダプタの MTU を 7900 に引き上げた（元: $origMtu。測定後に戻す）"
        } else {
            Write-Host "  [警告] MTU を 7900 にできなかった（現在 $now）。"
            Write-Host "         このアダプタがジャンボフレーム非対応の可能性がある。"
            Write-Host "         以下の測定値は経路ではなくアダプタの上限を見ている恐れがある。"
        }
    } else {
        Write-Host "  [警告] 管理者権限がないため MTU を引き上げられない（現在 $origMtu）。"
        Write-Host "         測定値は経路ではなく PC 側の上限になる可能性が高い。"
    }
} else {
    Write-Host "  送信元アダプタの MTU は $origMtu（引き上げ不要）"
}

if (Test-Mtu -Target $target -Mtu 7900) {
    $passMtu = 7900
    Write-Host "  7900 通過。ODU の設定上限どおり。"
} else {
    Write-Host "  7900 は通らない。二分探索で上限を特定する..."
    $lo = 576; $hi = 7900
    if (-not (Test-Mtu -Target $target -Mtu $lo)) {
        $passMtu = 0
    } else {
        while (($hi - $lo) -gt 1) {
            $mid = [math]::Floor(($lo + $hi) / 2)
            if (Test-Mtu -Target $target -Mtu $mid) { $lo = $mid } else { $hi = $mid }
        }
        $passMtu = $lo
    }
    Write-Host "  通過可能な最大 MTU: $passMtu"
}

Write-Host ""
if ($passMtu -ge 7900) {
    Write-Host "  [OK] MTU 7900 で問題なし。"
} elseif ($passMtu -ge 7000) {
    Write-Host "  [OK] MTU $passMtu まで通る。ODU の設定上限 7900 とほぼ一致しており、"
    Write-Host "       経路にジャンボフレームの制約は無い。ラボ側 (9100) より小さいので、"
    Write-Host "       frr_setup.sh の cr1-lere / lere-cr1 をこの値に合わせること。"
} elseif ($passMtu -ge 1500) {
    Write-Host "  [注意] MTU が $passMtu に制限されている。"
    if ((-not $mtuRaised) -and ($origMtu -lt 7900)) {
        Write-Host "         ただし送信元アダプタの MTU が $origMtu のままなので、"
        Write-Host "         これは経路ではなく PC 側の上限を見ている可能性が高い。"
        Write-Host "         アダプタの MTU を上げてから再測定すること。"
    } else {
        Write-Host "         送信元アダプタは引き上げ済みなので、経路上の機器"
        Write-Host "         （KeepLINK / 中継部 / ODU）がジャンボフレーム非対応。"
        Write-Host "         frr_setup.sh の cr1-lere / lere-cr1 をこの値に合わせるか、"
        Write-Host "         OSPF に mtu-ignore が必要になる（DBD で MTU 照合するため）。"
    }
} else {
    Write-Host "  [NG] MTU 測定に失敗、または極端に小さい。経路を確認すること。"
}

# アダプタの MTU を元に戻す
if ($mtuRaised) {
    netsh interface ipv4 set subinterface "$Adapter" mtu=$origMtu store=active | Out-Null
    Write-Host "  送信元アダプタの MTU を $origMtu に戻した"
}

# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "[3] スループット測定（CR_BW の根拠）"
Write-Hr

$iperf = Get-Command iperf3.exe -ErrorAction SilentlyContinue
if ([string]::IsNullOrWhiteSpace($Peer)) {
    Write-Host "  対向PCのIPが未指定のためスキップ。"
    Write-Host ""
    Write-Host "  測定するには対向PCを KeepLINK-C (ODU-D 側) に挿し、"
    Write-Host "    対向PC:  iperf3 -s   （IP を 192.168.1.200/24 に設定）"
    Write-Host "    こちら:  .\scripts\radwin_verify.ps1 -Adapter `"$Adapter`" -Peer 192.168.1.200"
    Write-Host ""
    Write-Host "  PCが1台しかない場合は、ODU 管理画面の Wireless Status にある"
    Write-Host "  TX/RX SpeedTest で各ホップ単体のスループットを測れる。"
} elseif ($null -eq $iperf) {
    Write-Host "  [NG] iperf3.exe が PATH にない。"
    Write-Host "       https://iperf.fr/iperf-download.php から Windows 版を入手し、"
    Write-Host "       展開先で実行するか PATH を通すこと。"
} else {
    Write-Host "  TCP で上限を把握:"
    & iperf3.exe -c $Peer -t 20 | Select-Object -Last 4 | ForEach-Object { Write-Host "    $_" }

    Write-Host ""
    Write-Host "  UDP で損失が出始める点を探す（実験は UDP なのでこちらを採用）:"
    foreach ($rate in @("500M","1G","1500M","2G")) {
        $line = (& iperf3.exe -c $Peer -u -b $rate -t 15 | Select-String "receiver" | Select-Object -Last 1)
        Write-Host ("    {0,-8} {1}" -f $rate, $line)
    }
    Write-Host ""
    Write-Host "  損失が出始める直前のレートが実効容量。"
    Write-Host "  CR_BW = 実効容量 x 0.9 とし、lab_config_c2.sh の"
    Write-Host "  CR1_BW / CR2_BW / CR3_BW を全て同じ値に揃えること。"
}

Write-Host ""
Write-Host "============================================================="
Write-Host " 完了。この出力を記録しておくこと（CR_BW と MTU の根拠になる）"
Write-Host "============================================================="
