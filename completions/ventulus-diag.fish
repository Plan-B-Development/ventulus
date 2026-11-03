# Fish completions for ventulus-diag
set -l cmds status headers cancel preflight report characterise discover validation
complete -c ventulus-diag -f
complete -c ventulus-diag -l socket -d 'Daemon socket path' -r -F
complete -c ventulus-diag -l version -d 'Print the version'
complete -c ventulus-diag -s h -l help -d 'Show help'
complete -c ventulus-diag -n "not __fish_seen_subcommand_from $cmds" -a status -d 'Daemon, thermal state and any running test'
complete -c ventulus-diag -n "not __fish_seen_subcommand_from $cmds" -a headers -d 'Headers and the tests each offers'
complete -c ventulus-diag -n "not __fish_seen_subcommand_from $cmds" -a cancel -d 'Cancel a running characterisation, discovery or probe'
complete -c ventulus-diag -n "not __fish_seen_subcommand_from $cmds" -a preflight -d "The daemon's safety verdict for one test"
complete -c ventulus-diag -n "not __fish_seen_subcommand_from $cmds" -a report -d 'PWM Test Reports'
complete -c ventulus-diag -n "not __fish_seen_subcommand_from $cmds" -a characterise -d "Sweep one header's PWM response"
complete -c ventulus-diag -n "not __fish_seen_subcommand_from $cmds" -a discover -d 'Find which tach follows one header'
complete -c ventulus-diag -n "not __fish_seen_subcommand_from $cmds" -a validation -d 'Validation sessions'
complete -c ventulus-diag -n "__fish_seen_subcommand_from report; and not __fish_seen_subcommand_from run list show export compare" -a 'run list show export compare'
complete -c ventulus-diag -n "__fish_seen_subcommand_from run" -l header -r -d 'Test only this header'
complete -c ventulus-diag -n "__fish_seen_subcommand_from run" -l test -r -a 'verify pairing sweep'
complete -c ventulus-diag -n "__fish_seen_subcommand_from run" -l stall-probe -r -d 'Also run the stall/restart probe (the fan may stop)'
complete -c ventulus-diag -n "__fish_seen_subcommand_from run" -l allow-fan-stop -r -d 'Allow the probe to stop this header'
complete -c ventulus-diag -n "__fish_seen_subcommand_from run" -l snapshot-only -d 'Record state, test nothing'
complete -c ventulus-diag -n "__fish_seen_subcommand_from run" -l notes -r -F -d 'Setup facts (JSON)'
complete -c ventulus-diag -n "__fish_seen_subcommand_from run" -l dry-run -d 'Print the plan'
complete -c ventulus-diag -n "__fish_seen_subcommand_from export compare" -l format -r -a 'markdown html json csv'
complete -c ventulus-diag -n "__fish_seen_subcommand_from export compare" -s o -l output -r -F
complete -c ventulus-diag -n "__fish_seen_subcommand_from preflight" -a 'verify pairing sweep probe'
complete -c ventulus-diag -n "__fish_seen_subcommand_from validation; and not __fish_seen_subcommand_from devices start status stop cancel marker measure list show export" -a 'devices start status stop cancel marker measure list show export'
complete -c ventulus-diag -n "__fish_seen_subcommand_from start" -l device -r
complete -c ventulus-diag -n "__fish_seen_subcommand_from start" -l kind -r -a 'validation lifecycle thermal'
complete -c ventulus-diag -n "__fish_seen_subcommand_from start" -l diagnostic -r -a 'verify characterization behaviour control-path'
complete -c ventulus-diag -n "__fish_seen_subcommand_from start" -l sweep-member -r
complete -c ventulus-diag -n "__fish_seen_subcommand_from start" -l meta -r
complete -c ventulus-diag -n "__fish_seen_subcommand_from start" -l auto-stop
complete -c ventulus-diag -n "__fish_seen_subcommand_from start" -l detach
complete -c ventulus-diag -n "__fish_seen_subcommand_from run characterise discover start" -l yes-change-fan-speeds -d 'Confirm this test may change fan speeds'
