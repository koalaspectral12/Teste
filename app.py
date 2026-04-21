import csv
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "Relatório de WhatsApp"
DEFAULT_MATERIALS = """cabo as120 12fo
cabo as120 6fo
alça branca"""

DEFAULT_FIELDS = """data
tecnico
material
quantidade
unidade
observacao"""

@dataclass
class Message:
    date: str
    time: str
    sender: str
    text: str

WHATSAPP_PATTERNS = [
    re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}),\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*-\s*([^:]+):\s*(.*)$"),
    re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{2,4}),\s*(\d{1,2}:\d{2}(?::\d{2})?)\]\s*([^:]+):\s*(.*)$"),
]

DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")
OBS_RE = re.compile(r"\b(?:obs|observacao|observação)\s*[:\-]\s*(.+)$", re.IGNORECASE)
TECH_RE = re.compile(r"\b(?:tecnico|técnico)\s*[:\-]\s*([\wÀ-ÿ .'-]+)", re.IGNORECASE)


def strip_accents(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))


def normalize(value: str) -> str:
    return strip_accents(value).lower().strip()


def parse_date(date_str: str) -> str:
    date_str = date_str.strip()
    parts = date_str.split("/")
    if len(parts[-1]) == 2:
        parts[-1] = "20" + parts[-1]
    try:
        dt = datetime.strptime("/".join(parts), "%d/%m/%Y")
        return dt.strftime("%d/%m/%Y")
    except ValueError:
        return date_str


def split_whatsapp_messages(raw_text: str):
    lines = raw_text.splitlines()
    messages = []
    current = None
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            if current:
                current.text += "\n"
            continue
        matched = None
        for pattern in WHATSAPP_PATTERNS:
            m = pattern.match(line)
            if m:
                matched = m
                break
        if matched:
            if current:
                messages.append(current)
            msg_date, msg_time, sender, text = matched.groups()
            current = Message(parse_date(msg_date), msg_time, sender.strip(), text.strip())
        else:
            if current:
                current.text += ("\n" if current.text else "") + line.strip()
            else:
                messages.append(Message("", "", "", line.strip()))
    if current:
        messages.append(current)
    if not messages and raw_text.strip():
        messages.append(Message("", "", "", raw_text.strip()))
    return messages


def extract_date(text: str, fallback_date: str = "") -> str:
    m = DATE_RE.search(text)
    if m:
        return parse_date(m.group(1))
    return fallback_date or "SEM_DATA"


def extract_tecnico(sender: str, text: str) -> str:
    m = TECH_RE.search(text)
    if m:
        return m.group(1).strip()
    return sender.strip() if sender else ""


def extract_observacao(text: str) -> str:
    m = OBS_RE.search(text)
    return m.group(1).strip() if m else ""


QUANTITY_PATTERNS = [
    re.compile(r"^\s*=\s*([0-9]+(?:[\.,][0-9]+)?)\s*([a-zA-ZÀ-ÿ]{0,10})"),
    re.compile(r"^\s*[:\-]\s*([0-9]+(?:[\.,][0-9]+)?)\s*([a-zA-ZÀ-ÿ]{0,10})"),
    re.compile(r"^\s+([0-9]+(?:[\.,][0-9]+)?)\s*([a-zA-ZÀ-ÿ]{0,10})"),
]


def parse_number(value: str) -> float:
    value = value.replace(".", "").replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return 0.0


def fmt_number(value: float) -> str:
    if abs(value - int(value)) < 0.000001:
        return str(int(value))
    return f"{value:.2f}".replace(".", ",")


def extract_material_entries(text: str, material_terms):
    original_text = text or ""
    lowered = normalize(original_text)
    found = []
    for material in material_terms:
        material = material.strip()
        if not material:
            continue
        norm_material = normalize(material)
        start = 0
        while True:
            idx = lowered.find(norm_material, start)
            if idx == -1:
                break
            after = original_text[idx + len(material): idx + len(material) + 30]
            quantity = None
            unit = ""
            for pattern in QUANTITY_PATTERNS:
                m = pattern.search(after)
                if m:
                    quantity = parse_number(m.group(1))
                    unit = (m.group(2) or "").strip()
                    break
            if quantity is not None:
                found.append({"material": material, "quantidade": quantity, "unidade": unit.upper()})
            start = idx + len(norm_material)
    return found


def build_reports(raw_text: str, material_terms):
    messages = split_whatsapp_messages(raw_text)
    detailed_rows = []
    summary = defaultdict(lambda: defaultdict(float))
    for msg in messages:
        text = msg.text.strip()
        if not text:
            continue
        msg_date = extract_date(text, msg.date)
        tecnico = extract_tecnico(msg.sender, text)
        observacao = extract_observacao(text)
        entries = extract_material_entries(text, material_terms)
        for entry in entries:
            key = entry["material"].strip()
            unit_key = entry["unidade"]
            combined_key = f"{key}||{unit_key}"
            summary[msg_date][combined_key] += entry["quantidade"]
            detailed_rows.append({
                "data": msg_date,
                "tecnico": tecnico,
                "material": key,
                "quantidade": entry["quantidade"],
                "unidade": unit_key,
                "observacao": observacao,
                "mensagem": text,
            })
    summary_rows = []
    for day in sorted(summary.keys(), key=lambda x: datetime.strptime(x, "%d/%m/%Y") if x != "SEM_DATA" else datetime.max):
        for combined_key, quantity in sorted(summary[day].items()):
            material, unit = combined_key.split("||")
            summary_rows.append({
                "data": day,
                "material": material,
                "quantidade_total": quantity,
                "unidade": unit,
            })
    return detailed_rows, summary_rows


def export_csv(file_path: Path, rows, headers):
    with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers, delimiter=";")
        writer.writeheader()
        for row in rows:
            converted = dict(row)
            for key, value in converted.items():
                if isinstance(value, float):
                    converted[key] = fmt_number(value)
            writer.writerow(converted)


def generate_text_report(summary_rows):
    if not summary_rows:
        return "Nenhum item encontrado."
    grouped = defaultdict(list)
    for row in summary_rows:
        grouped[row["data"]].append(row)
    lines = []
    for day in grouped:
        lines.append(f"Data: {day}")
        for item in grouped[day]:
            unit = f" {item['unidade']}" if item["unidade"] else ""
            lines.append(f"  - {item['material']}: {fmt_number(item['quantidade_total'])}{unit}")
        lines.append("")
    return "\n".join(lines).strip()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1200x760")
        self.minsize(1000, 680)
        self.detailed_rows = []
        self.summary_rows = []
        self._build_ui()

    def _build_ui(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)
        self.tab_chat = ttk.Frame(notebook)
        self.tab_config = ttk.Frame(notebook)
        self.tab_result = ttk.Frame(notebook)
        notebook.add(self.tab_chat, text="1. Conversa")
        notebook.add(self.tab_config, text="2. Configuração")
        notebook.add(self.tab_result, text="3. Resultado")
        self._build_chat_tab()
        self._build_config_tab()
        self._build_result_tab()

    def _build_chat_tab(self):
        top = ttk.Frame(self.tab_chat)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Label(top, text="Cole a conversa do WhatsApp ou importe um TXT exportado do grupo.", font=("Arial", 11, "bold")).pack(anchor="w")
        buttons = ttk.Frame(self.tab_chat)
        buttons.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Button(buttons, text="Importar TXT", command=self.import_txt).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Limpar", command=self.clear_chat).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Gerar relatório", command=self.process_chat).pack(side="left")
        self.chat_text = tk.Text(self.tab_chat, wrap="word", font=("Consolas", 11))
        self.chat_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _build_config_tab(self):
        container = ttk.Frame(self.tab_config)
        container.pack(fill="both", expand=True, padx=10, pady=10)
        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(1, weight=1)
        ttk.Label(container, text="Materiais a procurar no texto (um por linha)", font=("Arial", 11, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 6))
        ttk.Label(container, text="Campos esperados no relatório", font=("Arial", 11, "bold")).grid(row=0, column=1, sticky="w", pady=(0, 6))
        self.materials_text = tk.Text(container, wrap="word", font=("Consolas", 11), width=50)
        self.materials_text.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        self.materials_text.insert("1.0", DEFAULT_MATERIALS)
        self.fields_text = tk.Text(container, wrap="word", font=("Consolas", 11), width=50)
        self.fields_text.grid(row=1, column=1, sticky="nsew")
        self.fields_text.insert("1.0", DEFAULT_FIELDS)
        help_box = ttk.LabelFrame(container, text="Como funciona")
        help_box.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        help_text = (
            "1) Informe os nomes dos materiais que devem ser encontrados nas mensagens.\n"
            "2) O sistema tenta achar a quantidade logo após o material.\n"
            "   Exemplos reconhecidos: 'cabo as120 12fo = 350M' ou 'alça branca 14'.\n"
            "3) O relatório agrupa por data e soma o mesmo material no mesmo dia.\n"
            "4) Se o texto vier do WhatsApp exportado, o remetente pode virar o técnico automaticamente."
        )
        ttk.Label(help_box, text=help_text, justify="left").pack(anchor="w", padx=8, pady=8)

    def _build_result_tab(self):
        buttons = ttk.Frame(self.tab_result)
        buttons.pack(fill="x", padx=10, pady=10)
        ttk.Button(buttons, text="Exportar CSVs", command=self.export_results).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Copiar resumo", command=self.copy_report).pack(side="left")
        paned = ttk.Panedwindow(self.tab_result, orient="vertical")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        frame_top = ttk.Labelframe(paned, text="Resumo por dia")
        frame_bottom = ttk.Labelframe(paned, text="Detalhamento encontrado")
        paned.add(frame_top, weight=1)
        paned.add(frame_bottom, weight=1)
        self.report_text = tk.Text(frame_top, wrap="word", font=("Consolas", 11), height=14)
        self.report_text.pack(fill="both", expand=True, padx=8, pady=8)
        columns = ("data", "tecnico", "material", "quantidade", "unidade", "observacao")
        self.tree = ttk.Treeview(frame_bottom, columns=columns, show="headings")
        for col in columns:
            self.tree.heading(col, text=col.title())
            self.tree.column(col, width=160, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)

    def import_txt(self):
        file_path = filedialog.askopenfilename(title="Selecione o TXT exportado do WhatsApp", filetypes=[("Arquivos TXT", "*.txt"), ("Todos os arquivos", "*.*")])
        if not file_path:
            return
        try:
            content = Path(file_path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = Path(file_path).read_text(encoding="latin-1")
        self.chat_text.delete("1.0", tk.END)
        self.chat_text.insert("1.0", content)

    def clear_chat(self):
        self.chat_text.delete("1.0", tk.END)

    def process_chat(self):
        raw_text = self.chat_text.get("1.0", tk.END).strip()
        materials = [line.strip() for line in self.materials_text.get("1.0", tk.END).splitlines() if line.strip()]
        if not raw_text:
            messagebox.showwarning(APP_TITLE, "Cole a conversa ou importe um arquivo TXT antes de gerar o relatório.")
            return
        if not materials:
            messagebox.showwarning(APP_TITLE, "Informe pelo menos um material para procurar.")
            return
        self.detailed_rows, self.summary_rows = build_reports(raw_text, materials)
        self._refresh_result_views()
        if not self.summary_rows:
            messagebox.showinfo(APP_TITLE, "Nenhum material configurado foi encontrado no texto.")
        else:
            messagebox.showinfo(APP_TITLE, "Relatório gerado com sucesso.")

    def _refresh_result_views(self):
        self.report_text.delete("1.0", tk.END)
        self.report_text.insert("1.0", generate_text_report(self.summary_rows))
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in self.detailed_rows:
            self.tree.insert("", tk.END, values=(row["data"], row["tecnico"], row["material"], fmt_number(row["quantidade"]), row["unidade"], row["observacao"]))

    def export_results(self):
        if not self.summary_rows:
            messagebox.showwarning(APP_TITLE, "Gere o relatório antes de exportar.")
            return
        target_dir = filedialog.askdirectory(title="Selecione a pasta de exportação")
        if not target_dir:
            return
        target = Path(target_dir)
        detailed_file = target / "relatorio_detalhado.csv"
        summary_file = target / "relatorio_resumo_por_dia.csv"
        text_file = target / "relatorio_resumo.txt"
        export_csv(detailed_file, self.detailed_rows, ["data", "tecnico", "material", "quantidade", "unidade", "observacao", "mensagem"])
        export_csv(summary_file, self.summary_rows, ["data", "material", "quantidade_total", "unidade"])
        text_file.write_text(generate_text_report(self.summary_rows), encoding="utf-8")
        messagebox.showinfo(APP_TITLE, f"Arquivos exportados com sucesso:\n\n{detailed_file.name}\n{summary_file.name}\n{text_file.name}")

    def copy_report(self):
        report = self.report_text.get("1.0", tk.END).strip()
        if not report:
            messagebox.showwarning(APP_TITLE, "Não há resumo para copiar.")
            return
        self.clipboard_clear()
        self.clipboard_append(report)
        messagebox.showinfo(APP_TITLE, "Resumo copiado para a área de transferência.")


if __name__ == "__main__":
    app = App()
    app.mainloop()
