import tkinter as tk
import tkinter.filedialog as filedialog
import tkinter.messagebox as messagebox
import subprocess
import os
import shutil
import config
from utils import clean_path, parse_srt, format_timestamp

def show_srt_preview(app, srt_path, title="👁 Subtitle Preview"):
    if not srt_path:
        return messagebox.showerror("Preview", "No subtitle file selected!")
    if not os.path.exists(srt_path):
        return messagebox.showerror("Preview", f"File not found:\n{srt_path}")
    try:
        segments = parse_srt(srt_path)
    except Exception as e:
        return messagebox.showerror("Preview", f"Could not read file:\n{e}")

    pw = tk.Toplevel(app)
    pw.title(title)
    pw.geometry("620x520")
    pw.configure(bg=config.DARK_BG)
    pw.transient(app)
    pw.resizable(True, True)

    hf = tk.Frame(pw, bg=config.DARK_BG); hf.pack(fill=tk.X, padx=15, pady=(10, 4))
    tk.Label(hf, text=os.path.basename(srt_path), bg=config.DARK_BG, fg=config.VLC_ORANGE,
             font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
    tk.Label(hf, text=f"  {len(segments)} lines", bg=config.DARK_BG, fg="#888",
             font=("Segoe UI", 9)).pack(side=tk.LEFT)

    sf = tk.Frame(pw, bg=config.DARK_BG); sf.pack(fill=tk.X, padx=15, pady=(0, 4))
    search_var = tk.StringVar()
    tk.Label(sf, text="Search:", bg=config.DARK_BG, fg="#888", font=("Segoe UI", 8)).pack(side=tk.LEFT)
    search_entry = tk.Entry(sf, textvariable=search_var, width=28, bg="#2a2a2a", fg="white",
                            insertbackground="white", border=0, font=("Segoe UI", 9))
    search_entry.pack(side=tk.LEFT, padx=5, ipady=2)
    match_label = tk.Label(sf, text="", bg=config.DARK_BG, fg=config.VLC_ORANGE, font=("Segoe UI", 8))
    match_label.pack(side=tk.LEFT)

    tf = tk.Frame(pw, bg=config.DARK_BG); tf.pack(fill=tk.BOTH, expand=True, padx=15, pady=4)
    vsb = tk.Scrollbar(tf); vsb.pack(side=tk.RIGHT, fill=tk.Y)
    txt = tk.Text(tf, bg="#0d0d0d", fg="white", font=("Consolas", 9), yscrollcommand=vsb.set,
                  border=0, highlightthickness=0, wrap=tk.WORD, selectbackground=config.VLC_ORANGE)
    txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    vsb.config(command=txt.yview)

    txt.tag_configure("idx",   foreground="#555",     font=("Consolas", 8))
    txt.tag_configure("time",  foreground=config.VLC_ORANGE, font=("Consolas", 9, "bold"))
    txt.tag_configure("body",  foreground="#e8e8e8",  font=("Consolas", 9))
    txt.tag_configure("sep",   foreground="#252525")
    txt.tag_configure("found", background=config.VLC_ORANGE, foreground="black")

    for seg in segments:
        txt.insert(tk.END, f"[{seg['index']}]  ", "idx")
        txt.insert(tk.END, f"{format_timestamp(seg['start'])}  →  {format_timestamp(seg['end'])}\n", "time")
        txt.insert(tk.END, f"{seg['text']}\n", "body")
        txt.insert(tk.END, "─" * 70 + "\n", "sep")
    txt.config(state=tk.DISABLED)

    def do_search(*_):
        txt.tag_remove("found", "1.0", tk.END)
        q = search_var.get().strip()
        if not q:
            match_label.config(text=""); return
        count, start = 0, "1.0"
        while True:
            pos = txt.search(q, start, nocase=True, stopindex=tk.END)
            if not pos: break
            end = f"{pos}+{len(q)}c"
            txt.tag_add("found", pos, end)
            if count == 0: txt.see(pos)
            count += 1
            start = end
        match_label.config(text=f"{count} match{'es' if count != 1 else ''}")
    search_var.trace_add("write", do_search)
    search_entry.bind("<Return>", do_search)

    bf = tk.Frame(pw, bg=config.DARK_BG); bf.pack(fill=tk.X, padx=15, pady=(4, 10))
    tk.Button(bf, text="📋 Copy All", bg="#333", fg="white", relief=tk.FLAT, font=("Segoe UI", 9), padx=8, pady=4,
              command=lambda: (pw.clipboard_clear(), pw.clipboard_append(open(srt_path, encoding='utf-8').read()))
             ).pack(side=tk.LEFT, padx=(0, 5))
    tk.Button(bf, text="📝 Open in Notepad", bg="#333", fg="white", relief=tk.FLAT, font=("Segoe UI", 9), padx=8, pady=4,
              command=lambda: subprocess.Popen(["notepad", srt_path])).pack(side=tk.LEFT)
    tk.Button(bf, text="Close", bg=config.VLC_ORANGE, fg="black", relief=tk.FLAT, font=("Segoe UI", 9, "bold"),
              padx=12, pady=4, command=pw.destroy).pack(side=tk.RIGHT)

def show_style_preview(app, style_vars):
    pw = tk.Toplevel(app)
    pw.title("🖥 Live Style Preview")
    pw.geometry("660x420")
    pw.configure(bg=config.DARK_BG)
    pw.transient(app)
    pw.resizable(False, False)

    tk.Label(pw, text="Live Style Preview", bg=config.DARK_BG, fg=config.VLC_ORANGE,
             font=("Segoe UI", 11, "bold")).pack(pady=(10, 4))
    tk.Label(pw, text="Preview updates automatically as you change settings",
             bg=config.DARK_BG, fg="#555", font=("Segoe UI", 8)).pack(pady=(0, 6))

    CWIDTH, CHEIGHT = 620, 280
    canvas = tk.Canvas(pw, width=CWIDTH, height=CHEIGHT, bg="#000",
                       highlightthickness=2, highlightbackground="#333")
    canvas.pack(padx=20)

    def get_initial_text():
        sp = clean_path(style_vars['srt_path'].get().strip())
        if sp and os.path.exists(sp):
            segs = parse_srt(sp)
            if segs: return segs[0]['text'].replace('\n', ' ')[:60]
        return "Sample subtitle text – preview here"

    def draw():
        canvas.delete("all")
        canvas.create_rectangle(0, 0, CWIDTH, CHEIGHT, fill="#444444", outline="")
        for x in range(0, CWIDTH, 20):
            for y in range(0, CHEIGHT, 20):
                if (x // 20 + y // 20) % 2 == 0:
                    canvas.create_rectangle(x, y, x+20, y+20, fill="#3c3c3c", outline="")

        canvas.create_rectangle(0, 0, CWIDTH, 25, fill="#111111", outline="")
        canvas.create_rectangle(0, CHEIGHT-25, CWIDTH, CHEIGHT, fill="#111111", outline="")

        font_name   = style_vars['font_name'].get() or "Arial"
        font_size   = style_vars['font_size'].get()
        weight      = " ".join(filter(None, ["bold" if style_vars['bold'].get() else "", "italic" if style_vars['italic'].get() else ""])) or "normal"
        try:
            fnt = (font_name, -font_size, weight)
            tmp = canvas.create_text(CWIDTH//2, 10, text="A", fill="#000000", font=fnt)
            canvas.delete(tmp)
        except Exception:
            fnt = ("Arial", -font_size, weight)

        text_col    = style_vars['text_color'].get()
        outline_col = style_vars['outline_color'].get()
        outline_sz  = style_vars['outline_sz'].get()
        shadow_sz   = style_vars['shadow'].get()
        pos         = style_vars['position'].get()
        display_txt = entry_widget.get().strip() or " "

        cx, cy = CWIDTH // 2, 38 if pos == "top" else CHEIGHT - 38

        if style_vars['bg'].get():
            tmp = canvas.create_text(cx, cy, text=display_txt, font=fnt, anchor="center")
            bbox = canvas.bbox(tmp)
            canvas.delete(tmp)
            if bbox:
                x1, y1, x2, y2 = bbox
                canvas.create_rectangle(x1 - 10, y1 - 2, x2 + 10, y2 + 2, fill="#111111", outline="")

        if shadow_sz > 0:
            for d in range(shadow_sz, 0, -1):
                alpha = "#1a1a1a" if d == shadow_sz else "#0d0d0d"
                canvas.create_text(cx + d*2, cy + d*2, text=display_txt, fill=alpha, font=fnt, anchor="center")

        if outline_sz > 0:
            for dx in range(-outline_sz, outline_sz + 1):
                for dy in range(-outline_sz, outline_sz + 1):
                    if abs(dx) + abs(dy) >= outline_sz:
                        canvas.create_text(cx + dx, cy + dy, text=display_txt, fill=outline_col, font=fnt, anchor="center")

        canvas.create_text(cx, cy, text=display_txt, fill=text_col, font=fnt, anchor="center")
        indicator = "▲ Top" if pos == "top" else "▼ Bottom"
        canvas.create_text(CWIDTH - 8, CHEIGHT - 8, text=indicator, fill="#333", font=("Segoe UI", 7), anchor="se")

    ctrl = tk.Frame(pw, bg=config.DARK_BG); ctrl.pack(fill=tk.X, padx=20, pady=8)
    tk.Label(ctrl, text="Preview text:", bg=config.DARK_BG, fg="#888", font=("Segoe UI", 9)).pack(side=tk.LEFT)
    entry_widget = tk.Entry(ctrl, width=32, bg="#2a2a2a", fg="white", insertbackground="white", border=0, font=("Segoe UI", 9))
    entry_widget.insert(0, get_initial_text())
    entry_widget.pack(side=tk.LEFT, padx=6, ipady=2)
    tk.Button(ctrl, text="Use 1st subtitle line", bg="#252525", fg="#aaa", relief=tk.FLAT, font=("Segoe UI", 8), padx=6, pady=3,
              command=lambda: [entry_widget.delete(0, tk.END), entry_widget.insert(0, get_initial_text()), draw()]
             ).pack(side=tk.LEFT, padx=4)

    def live_update(*args):
        if canvas.winfo_exists(): draw()

    entry_widget.bind("<KeyRelease>", live_update)
    pw.live_update_ref = live_update 
    
    traces = []
    def add_trace(var):
        cb = var.trace_add("write", live_update)
        traces.append((var, cb))

    for key, var in style_vars.items():
        if key != 'srt_path': add_trace(var)

    def on_close():
        for key, var in style_vars.items():
            if key != 'srt_path':
                try: var.trace_remove("write", traces.pop(0)[1])
                except: pass
        pw.destroy()

    pw.protocol("WM_DELETE_WINDOW", on_close)
    draw()

def open_history(app, populate_tabs_cb):
    hw = tk.Toplevel(app)
    hw.title("Subtitle History")
    hw.geometry("540x400")
    hw.configure(bg=config.DARK_BG)
    hw.transient(app)

    tk.Label(hw, text="Generated Subtitles History", bg=config.DARK_BG, fg=config.VLC_ORANGE,
             font=("Segoe UI", 12, "bold")).pack(pady=10)

    lf = tk.Frame(hw, bg=config.DARK_BG); lf.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
    sb = tk.Scrollbar(lf); sb.pack(side=tk.RIGHT, fill=tk.Y)
    lb = tk.Listbox(lf, bg=config.PANEL_BG, fg="white", yscrollcommand=sb.set, selectbackground=config.VLC_ORANGE,
                    selectforeground="black", border=0, highlightthickness=1, highlightbackground="#333", font=("Segoe UI", 9))
    lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    sb.config(command=lb.yview)

    def refresh():
        lb.delete(0, tk.END)
        if os.path.exists(config.SUB_DIR):
            files = sorted([f for f in os.listdir(config.SUB_DIR) if f.lower().endswith(('.srt', '.ass'))],
                           key=lambda x: os.path.getmtime(os.path.join(config.SUB_DIR, x)), reverse=True)
            for f in files: lb.insert(tk.END, f)
    refresh()

    def load_sel():
        sel = lb.curselection()
        if not sel: return
        populate_tabs_cb(os.path.join(config.SUB_DIR, lb.get(sel[0])))
        messagebox.showinfo("Loaded", "Subtitle loaded into all tabs!", parent=hw)

    def del_sel():
        sel = lb.curselection()
        if not sel: return
        fn = lb.get(sel[0])
        if messagebox.askyesno("Confirm", f"Delete '{fn}'?", parent=hw):
            os.remove(os.path.join(config.SUB_DIR, fn)); refresh()

    def export_sel():
        sel = lb.curselection()
        if not sel: return
        fn  = lb.get(sel[0])
        ext = os.path.splitext(fn)[1]
        dst = filedialog.asksaveasfilename(defaultextension=ext, initialfile=fn, title="Save As…", filetypes=[("Subtitle", f"*{ext}")], parent=hw)
        if dst:
            shutil.copy(os.path.join(config.SUB_DIR, fn), dst)
            messagebox.showinfo("Success", "Exported successfully!", parent=hw)

    bf = tk.Frame(hw, bg=config.DARK_BG); bf.pack(fill=tk.X, pady=10, padx=15)
    for txt, cmd, col in [
        ("📂 Load into Tabs", load_sel,  "#2196F3"),
        ("💾 Save As…",       export_sel, "#4CAF50"),
        ("🗑️ Delete",          del_sel,   "#cc0000"),
        ("📁 Open Folder",    lambda: os.startfile(config.SUB_DIR), "#444"),
    ]:
        tk.Button(bf, text=txt, bg=col, fg="white", font=("Segoe UI", 9, "bold"), relief=tk.FLAT, command=cmd, padx=6, pady=5).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=3)