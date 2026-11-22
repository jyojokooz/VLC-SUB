import re

content = open('main.py', 'r', encoding='utf-8').read()

# These handlers have set_progress_indeterminate(False) before showerror
INDETERMINATE_HANDLERS = [
    ('Auto-Sync Error', 'Auto-sync failed.'),
    ('Sync Error',      'Sync failed.'),
    ('Export Error',    'Export failed.'),
    ('Embedding Error', 'Burn failed.'),
]

for title, status_msg in INDETERMINATE_HANDLERS:
    old = (
        '        except Exception as e:\n'
        '            set_progress_indeterminate(False)\n'
        f'            app.after(0, lambda: messagebox.showerror("{title}", str(e)))\n'
        f'            update_status("❌ {status_msg}")\n'
        '            app.after(0, lambda: stage_label.config(text="❌ Failed", fg="#ff4444"))'
    )
    new = (
        '        except Exception as e:\n'
        '            set_progress_indeterminate(False)\n'
        '            _err = str(e)\n'
        '            if "⏹ Stopped" in _err:\n'
        '                update_status("⏹ Stopped.")\n'
        '                app.after(0, lambda: stage_label.config(text="⏹ Stopped", fg="#888"))\n'
        '                app.after(0, lambda: progress_var.set(0))\n'
        '                app.after(0, lambda: progress_label.config(text=""))\n'
        '            else:\n'
        f'                app.after(0, lambda: messagebox.showerror("{title}", _err))\n'
        f'                update_status("❌ {status_msg}")\n'
        '                app.after(0, lambda: stage_label.config(text="❌ Failed", fg="#ff4444"))'
    )
    if old in content:
        content = content.replace(old, new)
        print(f'Patched: {title}')
    else:
        print(f'NOT FOUND: {title}')

open('main.py', 'w', encoding='utf-8').write(content)
print('Done.')
