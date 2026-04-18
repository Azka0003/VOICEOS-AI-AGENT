import os
import json
import threading
from openpyxl import load_workbook, Workbook
from openpyxl.styles import PatternFill, Font

# Formatting constants
FILL_GREEN  = PatternFill("solid", fgColor="92D050")
FILL_YELLOW = PatternFill("solid", fgColor="FFFF00")
FILL_RED    = PatternFill("solid", fgColor="FF0000")
FILL_HEADER = PatternFill("solid", fgColor="2F4F8F")
FONT_HEADER = Font(bold=True, color="FFFFFF")

class ExcelTool:
    """
    Excel Tool for DebtPilot.
    Handles all reading and writing to backend/data/invoices.xlsx in a thread-safe manner.
    """
    
    _lock = threading.Lock()

    def __init__(self, filepath="data/invoices.xlsx"):
        """
        Initializes the Excel tool. Creates the file and formats headers if it does not exist.
        """
        self.filepath = filepath
        if not os.path.exists(self.filepath):
            self._init_sheet()

    def _init_sheet(self):
        """
        Creates a new workbook, sets the sheet name to 'Invoices', applies header styling, and saves.
        """
        try:
            with self._lock:
                os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
                wb = Workbook()
                ws = wb.active
                ws.title = "Invoices"
                
                headers =[
                    "Invoice ID", "Client", "Amount (₹)", "Due Date",
                    "Days Overdue", "Status", "Contact Name", "Contact Email",
                    "Risk Score", "Risk Label", "Dispute", "Next Action"
                ]
                ws.append(headers)
                
                for col_num in range(1, 13):
                    cell = ws.cell(row=1, column=col_num)
                    cell.fill = FILL_HEADER
                    cell.font = FONT_HEADER
                    
                wb.save(self.filepath)
        except Exception as e:
            print(f"[EXCEL ERROR] _init_sheet: {e}")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SECTION 2: READ METHODS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def get_all_invoices(self) -> list:
        """
        Reads every data row from the sheet.
        Returns a list of dictionaries with correctly typed fields.
        """
        try:
            invoices =[]
            with self._lock:
                wb = load_workbook(self.filepath, data_only=True)
                if "Invoices" in wb.sheetnames:
                    ws = wb["Invoices"]
                else:
                    ws = wb.active
                    ws.title = "Invoices"
                    
                rows = list(ws.iter_rows(min_row=2, values_only=True))
                
            for row in rows:
                if not row[0]:  # Skip empty rows
                    continue
                
                # Handle possible datetime objects for Due Date
                raw_date = row[3]
                if hasattr(raw_date, "strftime"):
                    due_date_str = raw_date.strftime("%Y-%m-%d")
                else:
                    due_date_str = str(raw_date).strip() if raw_date else ""

                invoices.append({
                    "id": str(row[0]).strip(),
                    "client": str(row[1]).strip() if row[1] else "",
                    "amount": int(row[2]) if row[2] is not None else 0,
                    "due_date": due_date_str,
                    "days_overdue": int(row[4]) if row[4] is not None else 0,
                    "status": str(row[5]).strip() if row[5] else "overdue",
                    "contact_name": str(row[6]).strip() if row[6] and str(row[6]).strip() != "None" else None,
                    "contact_email": str(row[7]).strip() if row[7] else "",
                    "risk_score": int(row[8]) if row[8] is not None else 0,
                    "risk_label": str(row[9]).strip() if row[9] else "",
                    "dispute_flag": True if row[10] and str(row[10]).strip().lower() == "yes" else False,
                    "next_action": str(row[11]).strip() if row[11] else ""
                })
            return invoices
        except Exception as e:
            print(f"[EXCEL ERROR] get_all_invoices: {e}")
            return[]

    def get_invoices_by_client(self, client_name: str) -> list:
        """
        Returns all invoices for a specific client (case-insensitive).
        """
        try:
            invoices = self.get_all_invoices()
            target = client_name.strip().lower()
            return [inv for inv in invoices if inv["client"].lower() == target]
        except Exception as e:
            print(f"[EXCEL ERROR] get_invoices_by_client: {e}")
            return[]

    def get_invoice_by_id(self, invoice_id: str) -> dict | None:
        """
        Returns a single invoice dictionary by its ID, or None if not found.
        """
        try:
            invoices = self.get_all_invoices()
            for inv in invoices:
                if inv["id"] == invoice_id:
                    return inv
            return None
        except Exception as e:
            print(f"[EXCEL ERROR] get_invoice_by_id: {e}")
            return None

    def get_overdue_invoices(self, min_days: int = 0) -> list:
        """
        Returns all invoices where days_overdue >= min_days.
        """
        try:
            invoices = self.get_all_invoices()
            return [inv for inv in invoices if inv["days_overdue"] >= min_days]
        except Exception as e:
            print(f"[EXCEL ERROR] get_overdue_invoices: {e}")
            return[]

    def get_high_risk_clients(self) -> list:
        """
        Returns a unique list of client names where risk_label == 'High'.
        """
        try:
            invoices = self.get_all_invoices()
            high_risk = {inv["client"] for inv in invoices if inv["risk_label"] == "High"}
            return list(high_risk)
        except Exception as e:
            print(f"[EXCEL ERROR] get_high_risk_clients: {e}")
            return[]

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SECTION 3: WRITE METHODS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def update_next_action(self, invoice_id: str, next_action: str) -> bool:
        """
        Updates the Next Action (col 12) for a specific invoice.
        """
        try:
            with self._lock:
                wb = load_workbook(self.filepath)
                ws = wb.active
                for row in range(2, ws.max_row + 1):
                    if ws.cell(row=row, column=1).value == invoice_id:
                        ws.cell(row=row, column=12).value = next_action
                        wb.save(self.filepath)
                        print(f"[EXCEL] Updated Next Action for {invoice_id}: {next_action}")
                        return True
                return False
        except Exception as e:
            print(f"[EXCEL ERROR] update_next_action: {e}")
            return False

    def update_risk_score(self, invoice_id: str, score: int, label: str) -> bool:
        """
        Updates Risk Score (col 9) and Risk Label (col 10) for an invoice.
        Applies conditional background color to the label cell.
        """
        try:
            with self._lock:
                wb = load_workbook(self.filepath)
                ws = wb.active
                for row in range(2, ws.max_row + 1):
                    if ws.cell(row=row, column=1).value == invoice_id:
                        ws.cell(row=row, column=9).value = score
                        
                        label_cell = ws.cell(row=row, column=10)
                        label_cell.value = label
                        
                        if label == "Low":
                            label_cell.fill = FILL_GREEN
                        elif label == "Medium":
                            label_cell.fill = FILL_YELLOW
                        elif label == "High":
                            label_cell.fill = FILL_RED
                            
                        wb.save(self.filepath)
                        return True
                return False
        except Exception as e:
            print(f"[EXCEL ERROR] update_risk_score: {e}")
            return False

    def update_contact_name(self, invoice_id: str, contact_name: str) -> bool:
        """
        Updates the Contact Name (col 7) for an invoice.
        """
        try:
            with self._lock:
                wb = load_workbook(self.filepath)
                ws = wb.active
                for row in range(2, ws.max_row + 1):
                    if ws.cell(row=row, column=1).value == invoice_id:
                        ws.cell(row=row, column=7).value = contact_name
                        wb.save(self.filepath)
                        return True
                return False
        except Exception as e:
            print(f"[EXCEL ERROR] update_contact_name: {e}")
            return False

    def append_invoice(self, invoice: dict) -> bool:
        """
        Appends a new invoice row to the end of the sheet.
        Applies currency formatting and risk label color.
        """
        try:
            with self._lock:
                wb = load_workbook(self.filepath)
                ws = wb.active
                
                row_data =[
                    invoice.get("id"),
                    invoice.get("client"),
                    invoice.get("amount"),
                    invoice.get("due_date"),
                    invoice.get("days_overdue"),
                    invoice.get("status", "overdue"),
                    invoice.get("contact_name"),
                    invoice.get("contact_email"),
                    invoice.get("risk_score"),
                    invoice.get("risk_label"),
                    "Yes" if invoice.get("dispute_flag") else "No",
                    invoice.get("next_action")
                ]
                
                ws.append(row_data)
                current_row = ws.max_row
                
                # Apply currency formatting to Amount (col 3)
                ws.cell(row=current_row, column=3).number_format = '#,##0'
                
                # Apply color fill to Risk Label (col 10)
                label = invoice.get("risk_label")
                label_cell = ws.cell(row=current_row, column=10)
                if label == "Low":
                    label_cell.fill = FILL_GREEN
                elif label == "Medium":
                    label_cell.fill = FILL_YELLOW
                elif label == "High":
                    label_cell.fill = FILL_RED
                    
                wb.save(self.filepath)
                return True
        except Exception as e:
            print(f"[EXCEL ERROR] append_invoice: {e}")
            return False

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SECTION 4: SYNC METHOD
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def sync_to_json(self) -> bool:
        """
        Reads the current state of the Excel sheet and writes it to mock_invoices.json.
        Preserves non-ASCII characters like ₹.
        """
        try:
            invoices = self.get_all_invoices()
            json_path = os.path.join(os.path.dirname(self.filepath), "mock_invoices.json")
            
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(invoices, f, indent=2, ensure_ascii=False)
                
            print(f"[EXCEL] Synced {len(invoices)} invoices to mock_invoices.json")
            return True
        except Exception as e:
            print(f"[EXCEL ERROR] sync_to_json: {e}")
            return False

# Export singleton instance for use by agents
excel_tool = ExcelTool()