# Bash completions for ventulus
_ventulus_gui() {
    local cur opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    opts="--socket --demo --help"

    if [[ ${cur} == -* ]]; then
        COMPREPLY=( $(compgen -W "${opts}" -- "${cur}") )
    fi
}
complete -F _ventulus_gui ventulus
