$data = [Console]::In.ReadToEnd() | ConvertFrom-Json
$remaining = if ($null -ne $data.context_window.remaining_percentage) { $data.context_window.remaining_percentage } else { 100 }
$pct = 100 - $remaining
$dir = Split-Path $data.workspace.current_dir -Leaf
"$dir | $($data.model.display_name) | $pct%"
