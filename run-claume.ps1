# Run claume from source without installing
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
& python -m claume.cli @args
