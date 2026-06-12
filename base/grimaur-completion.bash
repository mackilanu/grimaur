# Bash completion for grimaur helper
# Source this file or place it in bash_completion.d to enable `grimaur` completions.

_grimaur_completion()
{
    local cur prev words cword
    if ! _init_completion -n = 2>/dev/null; then
        words=("${COMP_WORDS[@]}")
        cword="${COMP_CWORD}"
        cur="${COMP_WORDS[COMP_CWORD]}"
        prev="${COMP_WORDS[COMP_CWORD-1]}"
    fi
    
    # Global options (can appear anywhere before subcommand)
    local global_opts="--dest-root --refresh --no-color --aur-rpc --git-mirror --use-ssh --shallow"
    
    # Find the subcommand (first non-option word after potential global options)
    local subcmd=""
    local subcmd_idx=0
    for ((i=1; i<${#words[@]}; i++)); do
        if [[ "${words[i]}" != -* ]] && [[ "${words[i]}" != "" ]]; then
            subcmd="${words[i]}"
            subcmd_idx=$i
            break
        fi
    done
    
    # Handle --dest-root value completion (directory path)
    if [[ "$prev" == "--dest-root" ]]; then
        mapfile -t COMPREPLY < <(compgen -d -- "$cur")
        return 0
    fi
    
    # If current word starts with -, complete options
    if [[ "$cur" == -* ]]; then
        local opts="$global_opts"
        
        case "$subcmd" in
            fetch)
                opts="$global_opts --force --repo-url"
                ;;
            install)
                opts="$global_opts --noconfirm --repo-url"
                ;;
            remove)
                opts="$global_opts --noconfirm --remove-cache"
                ;;
            update)
                opts="$global_opts --noconfirm --devel --global --system-only --index --download --install"
                ;;
            search)
                opts="$global_opts --limit --no-interactive --noconfirm --plain"
                ;;
            inspect)
                opts="$global_opts --target --full --repo-url --plain"
                ;;
            list)
                opts="$global_opts"
                ;;
            "")
                # No subcommand yet, only show global options
                opts="$global_opts"
                ;;
        esac
        
        mapfile -t COMPREPLY < <(compgen -W "$opts" -- "$cur")
        return 0
    fi
    
    # Handle --target value completion for inspect
    if [[ "$prev" == "--target" ]] && [[ "$subcmd" == "inspect" ]]; then
        mapfile -t COMPREPLY < <(compgen -W "info PKGBUILD SRCINFO" -- "$cur")
        return 0
    fi
    
    # Handle --limit value completion (just suggest some numbers)
    if [[ "$prev" == "--limit" ]]; then
        mapfile -t COMPREPLY < <(compgen -W "10 20 50 100" -- "$cur")
        return 0
    fi
    
    # If no subcommand yet, complete subcommands
    if [[ -z "$subcmd" ]]; then
        local subcmds="fetch install remove update search inspect list"
        mapfile -t COMPREPLY < <(compgen -W "$subcmds" -- "$cur")
        return 0
    fi
    
    # Complete package names based on subcommand
    case "$subcmd" in
        remove|update)
            # Complete with installed foreign packages
            local packages
            packages=$(pacman -Qmq 2>/dev/null)
            mapfile -t COMPREPLY < <(compgen -W "$packages" -- "$cur")
            ;;
        *)
            # install/fetch/inspect: AUR name is typed in full; search/list: no positional completion
            ;;
    esac
}

complete -F _grimaur_completion grimaur
