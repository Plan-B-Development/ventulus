# Bash completions for ventulus-diag
_ventulus_diag() {
    local cur prev cmd sub
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cmd="${COMP_WORDS[1]}"
    sub="${COMP_WORDS[2]}"

    if [[ ${prev} == --socket || ${prev} == --notes || ${prev} == -o || ${prev} == --output ]]; then
        COMPREPLY=( $(compgen -f -- "${cur}") )
        return
    fi
    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "status headers cancel preflight report characterise discover validation --socket --version --help" -- "${cur}") )
        return
    fi
    case "${cmd}" in
        report)
            if [[ ${COMP_CWORD} -eq 2 ]]; then
                COMPREPLY=( $(compgen -W "run list show export compare" -- "${cur}") )
            elif [[ ${sub} == run ]]; then
                COMPREPLY=( $(compgen -W "--header --test --stall-probe --allow-fan-stop --snapshot-only --notes --dry-run --yes-change-fan-speeds" -- "${cur}") )
            else
                COMPREPLY=( $(compgen -W "--format --output" -- "${cur}") )
            fi ;;
        characterise|discover)
            COMPREPLY=( $(compgen -W "--yes-change-fan-speeds" -- "${cur}") ) ;;
        preflight)
            [[ ${COMP_CWORD} -eq 3 ]] && COMPREPLY=( $(compgen -W "verify pairing sweep probe" -- "${cur}") ) ;;
        validation)
            if [[ ${COMP_CWORD} -eq 2 ]]; then
                COMPREPLY=( $(compgen -W "devices start status stop cancel marker measure list show export" -- "${cur}") )
            elif [[ ${sub} == start ]]; then
                COMPREPLY=( $(compgen -W "--device --kind --diagnostic --sweep-member --meta --auto-stop --detach --yes-change-fan-speeds" -- "${cur}") )
            fi ;;
    esac
}
complete -F _ventulus_diag ventulus-diag
