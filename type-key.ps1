<#
Types a key into the machine that run.bat started, through QEMU's monitor, so that a long key need not be typed by
hand: QEMU's window takes no pasting. Start the machine with the monitor on:

    $env:BOOS_MONITOR = "4455"
    .\run.bat

When the kernel asks for the key (what is typed there shows as stars), run this in a second PowerShell window, in the
same folder:

    .\type-key.ps1

Paste the key at the prompt (it does not show) and press Enter. The key goes to the machine one key at a time, as if it
were typed on a US keyboard, whatever this computer's own keyboard is. Nothing is pressed after it: look at the machine,
where the row shows the signs as stars (30 of them, and "and N more" for the rest), and press Enter there. If the
row shows the signs themselves, the kernel
was not asking for a key: take them away with Backspace, and do not send them. The key is not shown, kept or written
anywhere by this script; what the monitor says back, which repeats each key, is read and dropped.
#>
param([int]$Port = 4455)

# The names QEMU's monitor gives the keys of a US keyboard (its command sendkey), for each sign a key may hold.
$script:Plain = @{ '-' = 'minus'; '=' = 'equal'; '/' = 'slash'; '.' = 'dot'; ',' = 'comma'; ';' = 'semicolon';
    "'" = 'apostrophe'; '[' = 'bracket_left'; ']' = 'bracket_right'; '\' = 'backslash'; '`' = 'grave_accent' }
$script:Shifted = @{ '_' = 'minus'; '+' = 'equal'; '?' = 'slash'; '>' = 'dot'; '<' = 'comma'; ':' = 'semicolon';
    '"' = 'apostrophe'; '{' = 'bracket_left'; '}' = 'bracket_right'; '|' = 'backslash'; '~' = 'grave_accent';
    '!' = '1'; '@' = '2'; '#' = '3'; '$' = '4'; '%' = '5'; '^' = '6'; '&' = '7'; '*' = '8'; '(' = '9'; ')' = '0' }

function ConvertTo-KeyNames {
    # The monitor's names of the keys that type Text, one for each sign. A sign that no key types stops it all.
    param([string]$Text)
    $names = New-Object System.Collections.Generic.List[string]
    for ($at = 0; $at -lt $Text.Length; $at++) {
        $sign = [string]$Text[$at]
        if ($sign -cmatch '^[a-z0-9]$') { $names.Add($sign) }
        elseif ($sign -cmatch '^[A-Z]$') { $names.Add('shift-' + $sign.ToLower()) }
        elseif ($script:Plain.ContainsKey($sign)) { $names.Add($script:Plain[$sign]) }
        elseif ($script:Shifted.ContainsKey($sign)) { $names.Add('shift-' + $script:Shifted[$sign]) }
        else { throw "Sign $($at + 1) of the key is not one that a US keyboard types, so nothing was sent." }
    }
    return ,$names.ToArray()
}

function Send-KeyNames {
    # Types the keys through QEMU's monitor at Port on this computer, a little apart, as the project's tests do.
    param([string[]]$Names, [int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect('127.0.0.1', $Port)
    } catch {
        throw "Nothing answers at port $Port on this computer, so nothing was sent. Start the machine with `$env:BOOS_MONITOR = `"$Port`" and .\run.bat."
    }
    $sent = 0
    try {
        $stream = $client.GetStream()
        $buffer = New-Object byte[] 4096
        # Only QEMU's monitor greets with "QEMU": anything else at the port must not get the key.
        $heard = ''
        $deadline = (Get-Date).AddSeconds(5)
        while ((Get-Date) -lt $deadline -and $heard -notmatch 'QEMU') {
            if ($stream.DataAvailable) {
                $count = $stream.Read($buffer, 0, $buffer.Length)
                $heard += [Text.Encoding]::ASCII.GetString($buffer, 0, $count)
            } else {
                Start-Sleep -Milliseconds 50
            }
        }
        if ($heard -notmatch 'QEMU') {
            throw "What answers at port $Port is not QEMU's monitor, so nothing was sent."
        }
        foreach ($name in $Names) {
            $line = [Text.Encoding]::ASCII.GetBytes("sendkey $name`n")
            try {
                $stream.Write($line, 0, $line.Length)
            } catch {
                throw "The machine's monitor went away after $sent of $($Names.Length) signs: in the machine's window, take them away with Backspace, and do not press Enter."
            }
            $sent += 1
            if ($name.StartsWith('shift-')) { Start-Sleep -Milliseconds 220 } else { Start-Sleep -Milliseconds 90 }
            while ($stream.DataAvailable) { [void]$stream.Read($buffer, 0, $buffer.Length) }
        }
    } finally {
        $client.Close()
    }
}

# Dot-sourced (as a test does), only the two functions above are made.
if ($MyInvocation.InvocationName -eq '.') { return }

$secure = Read-Host -AsSecureString 'Paste the key (it does not show) and press Enter'
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer).Trim()
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    $secure.Dispose()
}
$count = $key.Length
if ($count -eq 0) {
    Write-Host 'No key was given, so nothing was sent.'
    exit 1
}
if ($count -gt 200) {
    $key = $null
    Write-Host "That is $count signs, and the kernel takes at most 200, so nothing was sent."
    exit 1
}
try {
    $names = ConvertTo-KeyNames $key
    $key = $null
    Write-Host "Typing $count signs into the machine, which takes about $([int][Math]::Ceiling($count * 0.2)) seconds."
    Send-KeyNames -Names $names -Port $Port
} catch {
    $key = $null
    Write-Host $_.Exception.Message
    exit 1
}
$shown = if ($count -gt 30) { "30 stars and `"and $($count - 30) more`"" } else { "$count stars" }
Write-Host "Done: $count signs. In the machine's window the row shows $shown. If it does, press Enter there."
