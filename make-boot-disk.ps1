# Makes the boot disk: one disk file that a PC, QEMU or VirtualBox can start
# boos from. Its list of parts names two parts: the start part, where a PC's
# startup program looks for a kernel to start, and boos's own part, where the
# kernel keeps its things. The kernel goes into the start part as the file
# EFI\BOOT\BOOTX64.EFI. `run-boot-disk.bat` calls this. Notes: docs/disk.md,
# "The boot disk".
#
#   powershell -NoProfile -File make-boot-disk.ps1 boot.img target\x86_64-unknown-uefi\debug\boos.efi
#
# The first time, the file is made and divided by make-disk.ps1, with a start
# part in front. After that, for a new kernel, only the start part is written
# again: boos's own part, with what the kernel keeps in it, is not touched.

param(
    # The disk file. It is made if it is not there yet.
    [Parameter(Mandatory = $true)][string]$Path,
    # The kernel to put into the start part.
    [Parameter(Mandatory = $true)][string]$Kernel,
    # How large a new disk file is made, in MB. The start part takes 64 of them,
    # boos's part most of the rest.
    [int]$Megabytes = 80
)

$ErrorActionPreference = "Stop"

$BlockSize = 512
$StartPartMegabytes = 64
# The kind numbers of the two parts, as make-disk.ps1 writes them.
$StartKind = [Guid]"c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
$BoosKind = [Guid]"261e771e-cc8b-4a7f-96d1-b57fd92eafea"

# The start part holds a FAT32 file system, the way Microsoft's FAT
# specification (fatgen103) lays it out. A block of the disk is a sector there;
# a cluster is the piece a file is kept in. Microsoft's own table gives one
# sector to a cluster for a part of up to 260 MB.
$SectorsPerCluster = 1
$ReservedSectors = 32       # The usual count for FAT32.
$FatCount = 2               # The table of clusters is kept twice.
$MediaByte = 0xF8           # "A disk that stays in its machine."
$InfoSector = 1             # The sector that counts the free clusters (FSInfo).
$CopySector = 6             # The copy of the first sector: always 6.
$RootCluster = 2            # The first cluster there is.
$EndOfChain = 0x0FFFFFFF    # "This is a file's last cluster."
$FewestClusters = 65525     # Fewer clusters than this would be FAT16, not FAT32.

# Writes a number into a list of bytes, lowest byte first.
function Set-Number([byte[]]$Bytes, [int]$At, [uint64]$Value, [int]$Length) {
    for ($i = 0; $i -lt $Length; $i++) {
        $Bytes[$At + $i] = [byte](($Value -shr (8 * $i)) -band 255)
    }
}

# Reads a number from a list of bytes, lowest byte first.
function Get-Number([byte[]]$Bytes, [int]$At, [int]$Length) {
    [uint64]$value = 0
    for ($i = $Length - 1; $i -ge 0; $i--) {
        $value = ($value -shl 8) -bor [uint64]$Bytes[$At + $i]
    }
    return $value
}

# Writes letters into a list of bytes.
function Set-Letters([byte[]]$Bytes, [int]$At, [string]$Letters) {
    $codes = [System.Text.Encoding]::ASCII.GetBytes($Letters)
    [Array]::Copy($codes, 0, $Bytes, $At, $codes.Length)
}

# One entry of a folder: a name of 8 and 3 letters, what it is, its first
# cluster, its length, and when it was written.
function New-Entry([string]$Name, [int]$Kind, [uint64]$Cluster, [uint64]$Length) {
    $entry = New-Object byte[] 32
    Set-Letters $entry 0 $Name
    $entry[11] = [byte]$Kind
    Set-Number $entry 14 $script:Time 2       # Made at,
    Set-Number $entry 16 $script:Date 2       # made on,
    Set-Number $entry 18 $script:Date 2       # last read on,
    Set-Number $entry 20 ($Cluster -shr 16) 2 # the first cluster's upper half,
    Set-Number $entry 22 $script:Time 2       # written at,
    Set-Number $entry 24 $script:Date 2       # written on,
    Set-Number $entry 26 ($Cluster -band 0xFFFF) 2
    Set-Number $entry 28 $Length 4
    return ,$entry
}

$Folder = 0x10
$File = 0x20

# Reads blocks of the disk file.
function Read-Blocks($Stream, [int64]$First, [int64]$Count) {
    $bytes = New-Object byte[] ($Count * $BlockSize)
    $Stream.Seek($First * $BlockSize, "Begin") | Out-Null
    $done = 0
    while ($done -lt $bytes.Length) {
        $got = $Stream.Read($bytes, $done, $bytes.Length - $done)
        if ($got -le 0) { break }
        $done += $got
    }
    return ,$bytes
}

# Writes into the start part, and only there: a write that would reach outside
# it stops the script before anything is written.
function Write-StartPart($Stream, [int64]$Sector, [byte[]]$Bytes) {
    $first = $script:StartFirst + $Sector
    $last = $first + [int64][Math]::Ceiling($Bytes.Length / $BlockSize) - 1
    if ($Sector -lt 0 -or $last -gt $script:StartLast) {
        throw "a write outside the start part was asked for (blocks $first to $last)"
    }
    $Stream.Seek($first * $BlockSize, "Begin") | Out-Null
    $Stream.Write($Bytes, 0, $Bytes.Length)
}

# ---------- The kernel ----------

if (-not (Test-Path -LiteralPath $Kernel -PathType Leaf)) {
    Write-Output "make-boot-disk: there is no kernel file $Kernel"
    exit 1
}
$kernelBytes = [System.IO.File]::ReadAllBytes((Get-Item -LiteralPath $Kernel).FullName)
if ($kernelBytes.Length -eq 0) {
    Write-Output "make-boot-disk: the kernel file $Kernel is empty"
    exit 1
}

# ---------- A new disk file ----------

if (-not (Test-Path -LiteralPath $Path)) {
    $made = [System.IO.File]::Create($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path))
    $made.SetLength([int64]$Megabytes * 1048576)
    $made.Close()
    & (Join-Path $PSScriptRoot "make-disk.ps1") -Path $Path -StartPartMegabytes $StartPartMegabytes
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $Path
        Write-Output "make-boot-disk: the new disk file could not be divided, so it was taken away again"
        exit 1
    }
}

# ---------- Finding the two parts ----------

$full = (Get-Item -LiteralPath $Path).FullName
try {
    $stream = [System.IO.File]::Open($full, "Open", "ReadWrite", "None")
} catch {
    Write-Output "make-boot-disk: $Path cannot be opened; is a machine still using it?"
    exit 1
}
try {
    $head = Read-Blocks $stream 1 1
    if ([System.Text.Encoding]::ASCII.GetString($head, 0, 8) -ne "EFI PART") {
        Write-Output "make-boot-disk: $Path has no list of parts, so it is left alone"
        exit 1
    }
    $entriesAt = [int64](Get-Number $head 72 8)
    $entryCount = [int64](Get-Number $head 80 4)
    $entrySize = [int64](Get-Number $head 84 4)
    $entryBlocks = [int64][Math]::Ceiling($entryCount * $entrySize / $BlockSize)
    $entries = Read-Blocks $stream $entriesAt $entryBlocks
    $starts = @()
    $boosParts = @()
    for ($i = 0; $i -lt $entryCount; $i++) {
        $at = [int]($i * $entrySize)
        $kindBytes = New-Object byte[] 16
        [Array]::Copy($entries, $at, $kindBytes, 0, 16)
        $kind = New-Object Guid (, $kindBytes)
        $part = @{ First = [int64](Get-Number $entries ($at + 32) 8); Last = [int64](Get-Number $entries ($at + 40) 8) }
        if ($kind -eq $StartKind) { $starts += $part }
        if ($kind -eq $BoosKind) { $boosParts += $part }
    }
    if ($starts.Count -ne 1 -or $boosParts.Count -ne 1) {
        Write-Output "make-boot-disk: $Path does not have exactly one start part and one part for boos, so it is left alone"
        exit 1
    }
    $script:StartFirst = $starts[0].First
    $script:StartLast = $starts[0].Last
    $boos = $boosParts[0]
    if ($StartLast -lt $StartFirst -or ($StartFirst -le $boos.Last -and $boos.First -le $StartLast)) {
        Write-Output "make-boot-disk: the start part of $Path overlaps boos's part, so it is left alone"
        exit 1
    }

    # ---------- The layout of the file system ----------

    $sectors = $StartLast - $StartFirst + 1
    # How many sectors each table of clusters needs: the specification's sum,
    # which leaves a little to spare.
    $perSector = [int64](((256 * $SectorsPerCluster) + $FatCount) / 2)
    $fatSectors = [int64][Math]::Floor((($sectors - $ReservedSectors) + ($perSector - 1)) / $perSector)
    $dataStart = $ReservedSectors + $FatCount * $fatSectors
    $clusters = [int64][Math]::Floor(($sectors - $dataStart) / $SectorsPerCluster)
    if ($clusters -lt $FewestClusters) {
        Write-Output "make-boot-disk: the start part of $Path is too small for FAT32, so it is left alone"
        exit 1
    }
    $clusterBytes = $SectorsPerCluster * $BlockSize
    $kernelClusters = [int64][Math]::Ceiling($kernelBytes.Length / $clusterBytes)
    # Three folders (the top one, EFI, BOOT) take a cluster each, and the kernel follows them.
    $efiCluster = $RootCluster + 1
    $bootCluster = $RootCluster + 2
    $kernelCluster = $RootCluster + 3
    $lastCluster = $kernelCluster + $kernelClusters - 1
    if ($lastCluster -gt $clusters + 1) {
        Write-Output "make-boot-disk: the kernel does not fit into the start part of $Path, so it is left alone"
        exit 1
    }

    # The time it is now, as the file system writes it.
    $now = Get-Date
    $script:Date = [uint64]((($now.Year - 1980) -shl 9) -bor ($now.Month -shl 5) -bor $now.Day)
    $script:Time = [uint64](($now.Hour -shl 11) -bor ($now.Minute -shl 5) -bor [int][Math]::Floor($now.Second / 2))

    # ---------- The first sectors ----------

    $first = New-Object byte[] $BlockSize
    $first[0] = 0xEB; $first[1] = 0x58; $first[2] = 0x90   # The jump the specification asks for.
    Set-Letters $first 3 "MSWIN4.1"                         # The name it advises.
    Set-Number $first 11 $BlockSize 2
    $first[13] = [byte]$SectorsPerCluster
    Set-Number $first 14 $ReservedSectors 2
    $first[16] = [byte]$FatCount
    # Bytes 17 to 20 stay 0: no fixed top folder, and the sector count is the long one below.
    $first[21] = [byte]$MediaByte
    # Bytes 22 and 23 stay 0: that is what makes this FAT32.
    Set-Number $first 24 63 2                               # Sectors to a track and heads: only
    Set-Number $first 26 255 2                              # old BIOS calls look at these.
    Set-Number $first 28 ([uint64]$StartFirst) 4            # The disk's blocks before the part.
    Set-Number $first 32 ([uint64]$sectors) 4
    Set-Number $first 36 ([uint64]$fatSectors) 4
    # Bytes 40 to 43 stay 0: both tables are kept the same, and the version is 0.0.
    Set-Number $first 44 $RootCluster 4
    Set-Number $first 48 $InfoSector 2
    Set-Number $first 50 $CopySector 2
    $first[64] = 0x80                                       # A hard disk, for old BIOS calls.
    $first[66] = 0x29                                       # The three fields after this one are there:
    Set-Number $first 67 ([uint64](Get-Random -Minimum 1 -Maximum ([int]::MaxValue))) 4   # a number of its own,
    Set-Letters $first 71 "NO NAME    "                     # no name,
    Set-Letters $first 82 "FAT32   "                        # and the kind, for people to read.
    $first[510] = 0x55
    $first[511] = 0xAA

    $info = New-Object byte[] $BlockSize
    Set-Number $info 0 0x41615252 4
    Set-Number $info 484 0x61417272 4
    Set-Number $info 488 ([uint64]($clusters - ($lastCluster - 1))) 4   # Free clusters.
    Set-Number $info 492 ([uint64]$lastCluster) 4                       # The last one given out.
    Set-Number $info 508 0xAA550000L 4                                  # (L: a number this large.)

    $reserved = New-Object byte[] ($ReservedSectors * $BlockSize)
    [Array]::Copy($first, 0, $reserved, 0, $BlockSize)
    [Array]::Copy($info, 0, $reserved, $InfoSector * $BlockSize, $BlockSize)
    [Array]::Copy($first, 0, $reserved, $CopySector * $BlockSize, $BlockSize)
    [Array]::Copy($info, 0, $reserved, ($CopySector + $InfoSector) * $BlockSize, $BlockSize)

    # ---------- The table of clusters ----------

    $fat = New-Object byte[] ($fatSectors * $BlockSize)
    Set-Number $fat 0 (0x0FFFFF00 -bor $MediaByte) 4   # Entry 0: the media byte, all other bits 1.
    Set-Number $fat 4 $EndOfChain 4                    # Entry 1: "taken", and its top bits say "clean".
    Set-Number $fat ($RootCluster * 4) $EndOfChain 4
    Set-Number $fat ($efiCluster * 4) $EndOfChain 4
    Set-Number $fat ($bootCluster * 4) $EndOfChain 4
    for ($cluster = $kernelCluster; $cluster -lt $lastCluster; $cluster++) {
        Set-Number $fat ([int]($cluster * 4)) ([uint64]($cluster + 1)) 4
    }
    Set-Number $fat ([int]($lastCluster * 4)) $EndOfChain 4

    # ---------- The folders ----------

    $top = New-Object byte[] $clusterBytes
    [Array]::Copy((New-Entry "EFI        " $Folder $efiCluster 0), 0, $top, 0, 32)
    $efi = New-Object byte[] $clusterBytes
    [Array]::Copy((New-Entry ".          " $Folder $efiCluster 0), 0, $efi, 0, 32)
    [Array]::Copy((New-Entry "..         " $Folder 0 0), 0, $efi, 32, 32)    # 0: the top folder.
    [Array]::Copy((New-Entry "BOOT       " $Folder $bootCluster 0), 0, $efi, 64, 32)
    $bootFolder = New-Object byte[] $clusterBytes
    [Array]::Copy((New-Entry ".          " $Folder $bootCluster 0), 0, $bootFolder, 0, 32)
    [Array]::Copy((New-Entry "..         " $Folder $efiCluster 0), 0, $bootFolder, 32, 32)
    [Array]::Copy((New-Entry "BOOTX64 EFI" $File $kernelCluster ([uint64]$kernelBytes.Length)), 0, $bootFolder, 64, 32)

    $kernelRoom = New-Object byte[] ($kernelClusters * $clusterBytes)
    [Array]::Copy($kernelBytes, 0, $kernelRoom, 0, $kernelBytes.Length)

    # ---------- Writing, into the start part only ----------

    function Get-ClusterSector([int64]$Cluster) { return $dataStart + ($Cluster - 2) * $SectorsPerCluster }
    Write-StartPart $stream 0 $reserved
    Write-StartPart $stream $ReservedSectors $fat
    Write-StartPart $stream ($ReservedSectors + $fatSectors) $fat
    Write-StartPart $stream (Get-ClusterSector $RootCluster) $top
    Write-StartPart $stream (Get-ClusterSector $efiCluster) $efi
    Write-StartPart $stream (Get-ClusterSector $bootCluster) $bootFolder
    Write-StartPart $stream (Get-ClusterSector $kernelCluster) $kernelRoom
    $stream.Flush()
} finally {
    $stream.Close()
}

Write-Output ("make-boot-disk: {0}: the start part, blocks {1} to {2}, holds EFI\BOOT\BOOTX64.EFI ({3} bytes); boos's part, blocks {4} to {5}, was not touched" -f $Path, $StartFirst, $StartLast, $kernelBytes.Length, $boos.First, $boos.Last)
exit 0
