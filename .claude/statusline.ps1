$data = [Console]::In.ReadToEnd() | ConvertFrom-Json
$pct = if ($null -ne $data.context_window.remaining_percentage) { $data.context_window.remaining_percentage } else { 100 }
$dir = Split-Path $data.workspace.current_dir -Leaf
"$dir | $($data.model.display_name) | $pct%"
