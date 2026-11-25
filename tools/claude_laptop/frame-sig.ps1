# Per-capture signatures of a run's frames\shot-NNNNNN.png (NXRT_VK_SHOT_DIR), Windows PowerShell 5.1, no extra package.
# Writes <Dir>\..\frames-sig.csv: present, mean luma, mean abs difference to the previous capture (0-255, on a
# 64x36 grey thumbnail), exact-repeat flag (thumbnail identical), and optionally a contact sheet.
param(
  [Parameter(Mandatory)][string]$Dir,
  [string]$Csv,
  [string]$Sheet,                 # contact sheet png (thumbnails 240x135, 10 per row)
  [int]$SheetStep = 1             # one capture out of N on the sheet
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
if (-not ('FrameSig2' -as [type])) {
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System; using System.Drawing; using System.Drawing.Imaging; using System.Drawing.Drawing2D; using System.Runtime.InteropServices;
public static class FrameSig2 {
  // box average straight from the pixels: the alpha of the Vulkan captures is ignored (often 0)
  public static byte[] Thumb(string path, int w, int h) {
    using (var src = new Bitmap(path)) {
      int W = src.Width, H = src.Height;
      var d = src.LockBits(new Rectangle(0, 0, W, H), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
      var raw = new byte[d.Stride * H]; Marshal.Copy(d.Scan0, raw, 0, raw.Length); src.UnlockBits(d);
      var sum = new long[w * h]; var cnt = new int[w * h];
      for (int y = 0; y < H; y++) { int ty = y * h / H; int row = y * d.Stride;
        for (int x = 0; x < W; x++) { int o = row + x * 4; int t = ty * w + x * w / W;
          sum[t] += (raw[o] * 29 + raw[o + 1] * 150 + raw[o + 2] * 77) >> 8; cnt[t]++; } }
      var grey = new byte[w * h];
      for (int i = 0; i < grey.Length; i++) grey[i] = (byte)(cnt[i] > 0 ? sum[i] / cnt[i] : 0);
      return grey;
    }
  }
  public static double Mean(byte[] a) { long s = 0; foreach (var v in a) s += v; return (double)s / a.Length; }
  public static double Diff(byte[] a, byte[] b) { if (a == null) return -1; long s = 0; for (int i = 0; i < a.Length; i++) s += Math.Abs(a[i] - b[i]); return (double)s / a.Length; }
}
'@
}
$files = Get-ChildItem -LiteralPath $Dir -Filter 'shot-*.png' | Where-Object { $_.Name -match '^shot-(\d+)\.png$' } | Sort-Object { [int]($_.Name -replace '^shot-(\d+)\.png$', '$1') }
if (-not $Csv) { $Csv = Join-Path (Split-Path -Parent $Dir) 'frames-sig.csv' }
$rows = New-Object System.Collections.Generic.List[string]; $rows.Add('present,luma,diff_prev,repeat')
$prev = $null
foreach ($f in $files) {
  $n = [int]($f.Name -replace '^shot-(\d+)\.png$', '$1')
  $t = [FrameSig2]::Thumb($f.FullName, 64, 36)
  $d = [FrameSig2]::Diff($prev, $t)
  $rows.Add([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0},{1:F2},{2:F3},{3}', $n, [FrameSig2]::Mean($t), $d, [int]($d -eq 0)))
  $prev = $t
}
[IO.File]::WriteAllLines($Csv, $rows)
"$($files.Count) captures -> $Csv"
if ($Sheet -and $files.Count) {
  $pick = @(); for ($i = 0; $i -lt $files.Count; $i += $SheetStep) { $pick += $files[$i] }
  $tw = 240; $th = 135; $cols = 10; $rowsN = [math]::Ceiling($pick.Count / $cols)
  $bmp = New-Object System.Drawing.Bitmap ($tw * $cols), ($th * $rowsN)
  $g = [System.Drawing.Graphics]::FromImage($bmp); $g.Clear([System.Drawing.Color]::Black)
  $font = New-Object System.Drawing.Font 'Consolas', 9
  for ($i = 0; $i -lt $pick.Count; $i++) {
    $img = [System.Drawing.Image]::FromFile($pick[$i].FullName)
    $x = ($i % $cols) * $tw; $y = [math]::Floor($i / $cols) * $th
    $g.DrawImage($img, $x, $y, $tw, $th); $img.Dispose()
    $g.DrawString(($pick[$i].Name -replace '^shot-0*(\d+)\.png$', '$1'), $font, [System.Drawing.Brushes]::Yellow, $x + 2, $y + 2)
  }
  $bmp.Save($Sheet, [System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $bmp.Dispose()
  "sheet -> $Sheet"
}
