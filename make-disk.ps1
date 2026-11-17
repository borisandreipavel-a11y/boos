# Divides a new, empty disk file into parts, the way the disks of PCs are
# divided: a list at the start of the disk says where each part begins and
# ends and what kind of part it is. `run.bat` calls this for a disk file it
# has just made. Notes: docs/disk.md.
#
#   powershell -NoProfile -File make-disk.ps1 disk.img
#
# It refuses a file that holds anything but zeros, so it cannot divide a disk
# file that is in use.

param(
    # The disk file to divide.
    [Parameter(Mandatory = $true)][string]$Path,
    # For tests: put a small part of the kind a PC starts from in front of
    # boos's part, this many MB large. 0 means none.
    [int]$StartPartMegabytes = 0
)

$ErrorActionPreference = "Stop"

# A block is 512 bytes. The list's entries take 32 blocks: 128 entries of
# 128 bytes each. Parts begin at a whole MB, which is block 2048.
$BlockSize = 512
$EntryCount = 128
$EntrySize = 128
$EntryBlocks = 32
$FirstPartBlock = 2048

# The kind number that says "this part belongs to boos". It was made up once,
# at random, for this kernel. The kernel looks for exactly this number.
$BoosKind = [Guid]"261e771e-cc8b-4a7f-96d1-b57fd92eafea"
# The kind number of the part a PC's startup program starts a kernel from.
$StartKind = [Guid]"c12a7328-f81f-11d2-ba4b-00a0c93ec93b"

# The check value the list carries (CRC-32). Built up bit by bit.
function Get-Check([byte[]]$Bytes) {
    [uint32]$check = 4294967295
    foreach ($byte in $Bytes) {
        $check = $check -bxor [uint32]$byte
        for ($bit = 0; $bit -lt 8; $bit++) {
            if (($check -band 1) -ne 0) {
                $check = ($check -shr 1) -bxor [uint32]3988292384
            } else {
                $check = $check -shr 1
            }
        }
    }
    return [uint32]($check -bxor [uint32]4294967295)
}

# Writes a number into a list of bytes, lowest byte first.
function Set-Number([byte[]]$Bytes, [int]$At, [uint64]$Value, [int]$Length) {
    for ($i = 0; $i -lt $Length; $i++) {
        $Bytes[$At + $i] = [byte](($Value -shr (8 * $i)) -band 255)
    }
}

# Fills in one entry of the list: the part's kind, a number of its own, its
# first and last block, and its name.
function Set-Entry([byte[]]$Entries, [int]$Number, [Guid]$Kind, [uint64]$First, [uint64]$Last, [string]$Name) {
    $at = $Number * $EntrySize
    [Array]::Copy($Kind.ToByteArray(), 0, $Entries, $at, 16)
    [Array]::Copy([Guid]::NewGuid().ToByteArray(), 0, $Entries, $at + 16, 16)
    Set-Number $Entries ($at + 32) $First 8
    Set-Number $Entries ($at + 40) $Last 8
    $letters = [System.Text.Encoding]::Unicode.GetBytes($Name)
    [Array]::Copy($letters, 0, $Entries, $at + 56, $letters.Length)
}

# Builds the list's head, for the copy at the start or the one at the end.
function New-Head([uint64]$Here, [uint64]$Other, [uint64]$EntriesAt, [byte[]]$DiskNumber, [uint64]$FirstUsable, [uint64]$LastUsable, [uint32]$EntriesCheck) {
    $head = New-Object byte[] $BlockSize
    [Array]::Copy([System.Text.Encoding]::ASCII.GetBytes("EFI PART"), 0, $head, 0, 8)
    Set-Number $head 8 65536 4            # The version of the list: 1.0.
    Set-Number $head 12 92 4              # The head is 92 bytes long.
    Set-Number $head 24 $Here 8           # The block this head lies in.
    Set-Number $head 32 $Other 8          # The block the other copy's head lies in.
    Set-Number $head 40 $FirstUsable 8    # The first and the last block a part may use.
    Set-Number $head 48 $LastUsable 8
    [Array]::Copy($DiskNumber, 0, $head, 56, 16)
    Set-Number $head 72 $EntriesAt 8      # Where the entries begin.
    Set-Number $head 80 $EntryCount 4
    Set-Number $head 84 $EntrySize 4
    Set-Number $head 88 $EntriesCheck 4
    # The head's own check value is worked out last, over its 92 bytes, with
    # the place for it still holding zeros.
    $check = Get-Check ([byte[]]($head[0..91]))
    Set-Number $head 16 $check 4
    return ,$head
}

if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    Write-Output "make-disk: there is no file $Path"
    exit 1
}
$file = Get-Item -LiteralPath $Path
$blocks = [uint64]($file.Length / $BlockSize)
if ($file.Length % $BlockSize -ne 0 -or $blocks -lt 8192) {
    Write-Output "make-disk: $Path must be a whole number of blocks and at least 4 MB"
    exit 1
}
# Is every byte of the file 0? Looking at the bytes one by one is slow here.
# Taken as a text, a file of zeros is nothing but the sign with number 0, and
# cutting that sign off its front leaves nothing.
$content = [System.IO.File]::ReadAllBytes($file.FullName)
if ([System.Text.Encoding]::ASCII.GetString($content).TrimStart([char]0).Length -ne 0) {
    Write-Output "make-disk: $Path is not empty, so it is left alone"
    exit 1
}

# The list's copy at the end takes the last 33 blocks: its entries, then its head.
$lastBlock = $blocks - 1
$firstUsable = [uint64](2 + $EntryBlocks)
$lastUsable = [uint64]($blocks - 2 - $EntryBlocks)

$entries = New-Object byte[] ($EntryCount * $EntrySize)
$next = 0
$boosFirst = [uint64]$FirstPartBlock
if ($StartPartMegabytes -gt 0) {
    $startBlocks = [uint64]($StartPartMegabytes * 2048)
    Set-Entry $entries $next $StartKind $boosFirst ($boosFirst + $startBlocks - 1) "start"
    $next++
    $boosFirst = $boosFirst + $startBlocks
}
if ($boosFirst -gt $lastUsable) {
    Write-Output "make-disk: $Path is too small for its parts"
    exit 1
}
Set-Entry $entries $next $BoosKind $boosFirst $lastUsable "boos"
$entriesCheck = Get-Check $entries
$diskNumber = [Guid]::NewGuid().ToByteArray()

# The first block: an old-style list with one entry that says "this disk is
# divided the newer way". Older programs then leave the disk alone.
$first = New-Object byte[] $BlockSize
$first[446 + 2] = 2                       # Where the old-style entry begins and ends,
$first[446 + 4] = 0xEE                    # its kind: "divided the newer way",
$first[446 + 5] = 0xFF
$first[446 + 6] = 0xFF
$first[446 + 7] = 0xFF
Set-Number $first (446 + 8) 1 4           # its first block,
$covered = [uint64][Math]::Min([uint64]($blocks - 1), [uint64]4294967295)
Set-Number $first (446 + 12) $covered 4   # and how many blocks it covers.
$first[510] = 0x55
$first[511] = 0xAA

$head = New-Head 1 $lastBlock 2 $diskNumber $firstUsable $lastUsable $entriesCheck
$copyHead = New-Head $lastBlock 1 ($lastUsable + 1) $diskNumber $firstUsable $lastUsable $entriesCheck

$stream = [System.IO.File]::Open($file.FullName, "Open", "ReadWrite")
try {
    $stream.Write($first, 0, $BlockSize)
    $stream.Write($head, 0, $BlockSize)
    $stream.Write($entries, 0, $entries.Length)
    $stream.Seek([int64](($lastUsable + 1) * $BlockSize), "Begin") | Out-Null
    $stream.Write($entries, 0, $entries.Length)
    $stream.Write($copyHead, 0, $BlockSize)
} finally {
    $stream.Close()
}
$megabytes = [uint64][Math]::Floor(($lastUsable - $boosFirst + 1) / 2048)
Write-Output "make-disk: $Path is divided; the part for boos is blocks $boosFirst to $lastUsable, $megabytes MB"
exit 0
