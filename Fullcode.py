import os
import json
import hashlib
import hmac
import secrets
import shutil
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, date, time as datetime_time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from PIL import Image, ImageTk, ImageOps
except ImportError:
    Image = None
    ImageTk = None
    ImageOps = None

APP_DIR = Path(__file__).resolve().parent
DATA_FILE = APP_DIR / "washapp.json"
RECEIPT_DIR = APP_DIR / "receipts"
QR_DIR = APP_DIR / "qr_codes"
PAYMENT_IMAGE_DIR = APP_DIR / "payment_references"
PAYMENT_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
MAX_PAYMENT_IMAGE_BYTES = 5 * 1024 * 1024
PAYMENT_QR_IMAGES = {
    "GCash": APP_DIR / "gcashQr.png",
    "Bank Transfer": APP_DIR / "bankTransferQr.png",
}
PAYMENT_METHODS = list(PAYMENT_QR_IMAGES)
REFUND_METHODS = ["GCash", "Bank Transfer"]
REFUND_STATUSES = ["Pending", "Processing", "Completed"]
PAYMENT_OPTION_DOWNPAYMENT = "Downpayment (30%)"
PAYMENT_OPTION_FULL = "Full Payment"

COLORS = {
    "bg": "#08111f",
    "card": "#101d2d",
    "card2": "#0b1624",
    "cyan": "#29d9ff",
    "button": "#119bc1",
    "button2": "#173247",
    "white": "#ffffff",
    "muted": "#9bb0c2",
    "green": "#2ea879",
    "red": "#a94452",
    "yellow": "#a87820",
}

PRICES = {
    "Basic Wash": {"Sedan": 130, "SUV": 180, "Van": 200, "Pick-up": 200, "Motorcycle": 100},
    "Wash + Vacuum": {"Sedan": 160, "SUV": 200, "Van": 230, "Pick-up": 230, "Motorcycle": 130},
    "Wash + Wax": {"Sedan": 250, "SUV": 300, "Van": 350, "Pick-up": 350, "Motorcycle": 180},
    "Premium Wash": {"Sedan": 350, "SUV": 400, "Van": 450, "Pick-up": 450, "Motorcycle": 250},
    "Engine Wash": {"Sedan": 450, "SUV": 500, "Van": 550, "Pick-up": 550, "Motorcycle": 300},
}
VEHICLES = ["Sedan", "SUV", "Van", "Pick-up", "Motorcycle"]
SERVICES = list(PRICES)
BAYS = [f"Bay {n}" for n in range(1, 6)]
TIMES = [f"{h}:00 {ampm}" for ampm, hours in (("AM", range(7, 12)), ("PM", range(12, 19))) for h in []]
TIMES = ["7:00 AM", "8:00 AM", "9:00 AM", "10:00 AM", "11:00 AM",
         "12:00 PM", "1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM", "5:00 PM", "6:00 PM"]
DOWNPAYMENT_RATE = 0.30
DOWNPAYMENT_EXCEEDED_MESSAGE = (
    "Error: You have exceeded the 30% down payment limit. "
    "This payment option is no longer available."
)
DOWNPAYMENT_COMPLETED_MESSAGE = (
    "Down payment already completed. The 30% payment option is no longer available."
)
ERROR_COLOR = "#ff4d4d"

try:
    BUSINESS_TZ = ZoneInfo("Asia/Manila")
except ZoneInfoNotFoundError:
    BUSINESS_TZ = timezone(timedelta(hours=8), "Philippine Time (UTC+08:00)")


def business_now():
    """Current real-world time in the business timezone (Philippine Time)."""
    return datetime.now(BUSINESS_TZ)


def slot_datetime(date_text, time_text):
    """Parse the UI date/time and return a timezone-aware Manila datetime."""
    day = datetime.strptime(date_text.strip(), "%m/%d/%Y").date()
    clock = datetime.strptime(time_text.strip(), "%I:%M %p").time()
    return datetime.combine(day, clock, tzinfo=BUSINESS_TZ)


def slot_is_future(date_text, time_text, now=None):
    """A reservation must be strictly later than the current Manila time."""
    now = now or business_now()
    try:
        return slot_datetime(date_text, time_text) > now
    except ValueError:
        return False


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 180_000)
    return salt.hex() + "$" + digest.hex()


def verify_password(password, stored):
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 180_000)
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):

        return stored == password


def money(value):
    return f"₱{float(value):,.2f}"


def format_timestamp(value):
    """Return a readable date and time for an ISO timestamp."""
    if not value:
        return "N/A"
    try:
        return datetime.fromisoformat(str(value)).strftime("%m/%d/%Y %I:%M:%S %p")
    except ValueError:
        return str(value)


def payment_status_label(total, confirmed, pending):
    """Derive the payment status from confirmed and still-pending amounts."""
    if confirmed > 0:
        return "Fully Paid" if confirmed + 0.005 >= float(total) else "Partially Paid"
    if pending > 0:
        return "Pending"
    return "Unpaid"


def service_name(display_value):
    """Return the service key from a dropdown label that may include its price."""
    return str(display_value).split(" — ", 1)[0]

def service_options(vehicle):
    """Build service dropdown labels with prices for the selected vehicle."""
    return [f"{service} — {money(PRICES[service][vehicle])}" for service in SERVICES]


def format_file_size(size):
    """Return a short human-readable file size."""
    size = int(size or 0)
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{max(1, size // 1024)} KB"


def refund_account_error(method, holder, account_number, bank_name=""):
    """Validate the account fields required for GCash or Bank Transfer."""
    method = str(method or "").strip()
    holder = " ".join(str(holder or "").split())
    account_number = str(account_number or "").strip()
    bank_name = " ".join(str(bank_name or "").split())
    digits = "".join(ch for ch in account_number if ch.isdigit())
    if method not in REFUND_METHODS:
        return "Please select GCash or Bank Transfer as the refund method."
    if len(holder) < 2:
        return "Please enter the account holder's full name."
    if method == "GCash":
        if not (10 <= len(digits) <= 13):
            return "Enter a valid GCash mobile number (10-13 digits)."
    else:
        if len(bank_name) < 2 or not any(ch.isalpha() for ch in bank_name):
            return "Enter a valid bank name."
        if not (6 <= len(digits) <= 20):
            return "Enter a valid bank account number (6-20 digits)."
    return ""


def refund_details_complete(method, holder, account_number, bank_name=""):
    """Whether a refund destination has all fields required for its method."""
    return refund_account_error(method, holder, account_number, bank_name) == ""


def normalize_refund_date(value):
    """Accept MM/DD/YYYY or YYYY-MM-DD and return an ISO date, or None if invalid."""
    text = str(value or "").strip()
    if not text:
        return ""
    for pattern in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def format_refund_date(value, fallback="Not recorded"):
    """Display an ISO refund date in the app's usual month/day/year format."""
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%m/%d/%Y")
    except ValueError:
        return text


def mask_account_number(value):
    """Mask an account number while keeping a short recognizable prefix/suffix."""
    text = str(value or "").strip()
    if len(text) <= 4:
        return "•" * len(text)
    if len(text) <= 8:
        return text[:2] + ("•" * (len(text) - 4)) + text[-2:]
    return text[:4] + ("•" * max(4, len(text) - 7)) + text[-3:]


def validate_payment_image(path):
    """Validate a payment reference image and return (ok, message)."""
    source = Path(str(path or ""))
    if not source.is_file():
        return False, "Please select a payment reference image from your device."
    extension = source.suffix.lower()
    if extension not in PAYMENT_IMAGE_EXTENSIONS:
        return False, "Invalid file type. Please upload a PNG, JPG, or JPEG image."
    try:
        size = source.stat().st_size
    except OSError:
        return False, "The selected image could not be read. Please choose another file."
    if size <= 0:
        return False, "The selected image is empty. Please choose a valid payment receipt image."
    if size > MAX_PAYMENT_IMAGE_BYTES:
        return False, (f"The selected image is too large ({format_file_size(size)}). "
                       f"Please upload an image no larger than {format_file_size(MAX_PAYMENT_IMAGE_BYTES)}.")
    try:
        with source.open("rb") as handle:
            header = handle.read(12)
    except OSError:
        return False, "The selected image could not be read. Please choose another file."
    is_png = header.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpeg = header.startswith(b"\xff\xd8\xff")
    if extension == ".png" and not is_png:
        return False, "The selected file is not a valid PNG image."
    if extension in (".jpg", ".jpeg") and not is_jpeg:
        return False, "The selected file is not a valid JPG/JPEG image."
    if Image is not None:
        try:
            with Image.open(source) as img:
                img.verify()
        except (OSError, ValueError):
            return False, "The selected file is not a valid image. Please choose another PNG, JPG, or JPEG file."
    return True, ""


def load_payment_image(path, max_width=320, max_height=200):
    """Load a payment image for preview, scaled to fit the given bounds."""
    source = Path(str(path or ""))
    if not source.is_file():
        return None
    if Image is not None and ImageTk is not None:
        try:
            with Image.open(source) as img:
                if ImageOps is not None:
                    img = ImageOps.exif_transpose(img)
                img = img.convert("RGB")
                img.thumbnail((max_width, max_height))
                return ImageTk.PhotoImage(img)
        except (OSError, ValueError):
            return None
    try:
        photo = tk.PhotoImage(file=str(source))
    except tk.TclError:
        return None
    width, height = photo.width(), photo.height()
    factor = max(1, (width + max_width - 1) // max_width, (height + max_height - 1) // max_height)
    if factor > 1:
        photo = photo.subsample(factor, factor)
    return photo


def load_payment_qr(method, subsample=2):
    """Load the QR image that belongs to the chosen payment method (2x2 subsample)."""
    path = PAYMENT_QR_IMAGES.get(method)
    if path is None or not path.exists():
        return None
    try:
        photo = tk.PhotoImage(file=str(path))
        if subsample > 1:
            photo = photo.subsample(subsample, subsample)
        return photo
    except tk.TclError:
        if Image is None or ImageTk is None:
            return None
        try:
            with Image.open(path) as img:
                img = img.convert("RGB")
                if subsample > 1:
                    img = img.reduce(subsample)
                return ImageTk.PhotoImage(img)
        except (OSError, ValueError):
            return None


def ensure_dirs():
    RECEIPT_DIR.mkdir(exist_ok=True)
    QR_DIR.mkdir(exist_ok=True)
    PAYMENT_IMAGE_DIR.mkdir(exist_ok=True)


class Store:
    """Keeps every record in a plain JSON file (washapp.json) - no database engine needed."""

    def __init__(self):
        ensure_dirs()
        self.data = {"users": [], "reservations": [], "payments": [], "refunds": [],
                     "notifications": []}
        self.load()
        self.seed_accounts()

    def load(self):
        """Read the JSON data file into memory; an unreadable file starts empty."""
        if not DATA_FILE.exists():
            return
        try:
            loaded = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(loaded, dict):
            return
        for key in self.data:
            if isinstance(loaded.get(key), list):
                self.data[key] = loaded[key]
        self._migrate_bank_transfer_fields()

    def _migrate_bank_transfer_fields(self):
        """Convert legacy bank-specific payment/refund method values to Bank Transfer."""
        changed = False
        for payment in self.data["payments"]:
            if str(payment.get("method") or "").strip().upper() == "AUB":
                payment["method"] = "Bank Transfer"
                changed = True
        for refund in self.data["refunds"]:
            if str(refund.get("refund_method") or "").strip().upper() == "AUB":
                refund["refund_method"] = "Bank Transfer"
                if not refund.get("bank_name"):
                    refund["bank_name"] = "AUB"
                changed = True
        for user in self.data["users"]:
            if str(user.get("refund_method") or "").strip().upper() == "AUB":
                user["refund_method"] = "Bank Transfer"
                if not user.get("refund_bank_name"):
                    user["refund_bank_name"] = "AUB"
                changed = True
        if changed:
            self.save()

    def save(self):
        """Write the records back to disk atomically so a crash cannot corrupt the file."""
        temp = DATA_FILE.with_name(DATA_FILE.name + ".tmp")
        try:
            temp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            os.replace(temp, DATA_FILE)
        except OSError:
            pass

    def seed_accounts(self):
        seeds = [
            ("admin", "Admin123!", "WASHAPP Administrator", "N/A", "admin"),
            ("demo", "demo123", "Demo Customer", "09000000000", "customer"),
        ]
        changed = False
        for username, password, full_name, contact, role in seeds:
            if not self.user(username):
                self.data["users"].append({
                    "username": username,
                    "password_hash": hash_password(password),
                    "full_name": full_name,
                    "contact": contact,
                    "role": role,
                    "created_at": business_now().isoformat(timespec="seconds"),
                })
                changed = True
        if changed:
            self.save()

    def user(self, username):
        for record in self.data["users"]:
            if record["username"] == username:
                return dict(record)
        return None

    def register(self, username, password, full_name, contact,
                 refund_method="", refund_account_name="", refund_account_number="",
                 refund_bank_name=""):
        refund_method = str(refund_method or "").strip()
        refund_account_name = " ".join(str(refund_account_name or "").split())
        refund_account_number = str(refund_account_number or "").strip()
        refund_bank_name = (" ".join(str(refund_bank_name or "").split())
                            if refund_method == "Bank Transfer" else "")
        problem = refund_account_error(
            refund_method, refund_account_name, refund_account_number, refund_bank_name)
        if problem:
            return False, problem
        self.data["users"].append({
            "username": username,
            "password_hash": hash_password(password),
            "full_name": full_name,
            "contact": contact,
            "role": "customer",
            "created_at": business_now().isoformat(timespec="seconds"),
            "refund_method": refund_method,
            "refund_account_name": refund_account_name,
            "refund_account_number": refund_account_number,
            "refund_bank_name": refund_bank_name,
        })
        self.save()
        return True, "Account created."

    def migrate_legacy_password(self, username, password):
        for record in self.data["users"]:
            if record["username"] == username:
                record["password_hash"] = hash_password(password)
                break
        self.save()

    def change_password(self, username, current_password, new_password):
        """Verify and update only the authenticated user's password hash."""
        user = self.user(username)
        if not user or not verify_password(current_password, user["password_hash"]):
            return False, "Your current password is incorrect."
        if len(new_password) < 6:
            return False, "Use a new password with at least 6 characters."
        if verify_password(new_password, user["password_hash"]):
            return False, "Your new password must be different from your current password."
        for record in self.data["users"]:
            if record["username"] == username:
                record["password_hash"] = hash_password(new_password)
                break
        self.save()
        return True, "Your password has been changed successfully."

    def update_user_refund_details(self, username, method, holder, account_number,
                                   bank_name=""):
        """Save a customer's preferred refund destination on their own account."""
        method = str(method or "").strip()
        holder = " ".join(str(holder or "").split())
        account_number = str(account_number or "").strip()
        bank_name = " ".join(str(bank_name or "").split()) if method == "Bank Transfer" else ""
        problem = refund_account_error(method, holder, account_number, bank_name)
        if problem:
            return False, problem
        user_record = None
        for record in self.data["users"]:
            if record.get("username") == username:
                user_record = record
                break
        if not user_record or user_record.get("role") != "customer":
            return False, "That customer account could not be found."
        user_record["refund_method"] = method
        user_record["refund_account_name"] = holder
        user_record["refund_account_number"] = account_number
        user_record["refund_bank_name"] = bank_name
        now = business_now().isoformat(timespec="seconds")
        for refund in self.data["refunds"]:
            if (refund.get("username") == username
                    and refund.get("status") != "Completed"):
                refund["refund_method"] = method
                refund["account_holder"] = holder
                refund["account_number"] = account_number
                refund["bank_name"] = bank_name
                refund["updated_at"] = now
        self.save()
        return True, "Your payment and refund details have been updated."

    def next_notification_id(self):
        numbers = []
        for record in self.data["notifications"]:
            suffix = str(record.get("notification_id") or "").split("-")[-1]
            if suffix.isdigit():
                numbers.append(int(suffix))
        return f"NOTIF-{(max(numbers) if numbers else 0) + 1:04d}"

    def add_notification(self, username, title, message, related_type=None, related_id=None):
        """Store a private notification for a specific user account."""
        record = {
            "notification_id": self.next_notification_id(),
            "username": username,
            "title": title,
            "message": message,
            "related_type": related_type,
            "related_id": related_id,
            "created_at": business_now().isoformat(timespec="seconds"),
            "read_at": None,
        }
        self.data["notifications"].append(record)
        self.save()
        return dict(record)

    def notifications_for_user(self, username, limit=None):
        rows = [dict(r) for r in self.data["notifications"]
                if r.get("username") == username]
        rows.sort(key=lambda r: (str(r.get("created_at") or ""),
                                 str(r.get("notification_id") or "")), reverse=True)
        return rows[:limit] if limit else rows

    def mark_notification_read(self, notification_id, username):
        for record in self.data["notifications"]:
            if (str(record.get("notification_id")) == str(notification_id)
                    and record.get("username") == username):
                if not record.get("read_at"):
                    record["read_at"] = business_now().isoformat(timespec="seconds")
                    self.save()
                return True
        return False

    def mark_all_notifications_read(self, username):
        now = business_now().isoformat(timespec="seconds")
        changed = False
        for record in self.data["notifications"]:
            if record.get("username") == username and not record.get("read_at"):
                record["read_at"] = now
                changed = True
        if changed:
            self.save()
        return changed

    def reservations_for_user(self, username):
        rows = [r for r in self.data["reservations"] if r["username"] == username]
        return [dict(r) for r in self._newest_first(rows)]

    def all_reservations(self, status=None):
        rows = list(self.data["reservations"])
        if status and status != "All":
            rows = [r for r in rows if r["status"] == status]
        result = []
        for record in self._newest_first(rows):
            row = dict(record)
            label, confirmed, pending, remaining = self.payment_status(record["reservation_id"])
            row["verified_paid"] = confirmed
            row["remaining_balance"] = remaining
            row["payment_status"] = label
            row["latest_payment_status"] = label
            result.append(row)
        return result

    def get_reservation(self, reservation_id):
        for record in self.data["reservations"]:
            if record["reservation_id"] == reservation_id:
                return dict(record)
        return None

    def bay_available(self, bay, booking_date, booking_time, exclude_id=None):
        if not slot_is_future(booking_date, booking_time):
            return False
        for record in self.data["reservations"]:
            if record["reservation_id"] == exclude_id:
                continue
            if (record["bay"] == bay and record["booking_date"] == booking_date
                    and record["booking_time"] == booking_time
                    and record["status"] in ("Pending", "Approved")):
                return False
        return True

    def next_reservation_id(self):
        numbers = []
        for record in self.data["reservations"]:
            suffix = str(record["reservation_id"]).split("-")[-1]
            if suffix.isdigit():
                numbers.append(int(suffix))
        return f"RES-{(max(numbers) if numbers else 0) + 1:04d}"

    def create_reservation(self, values):
        """Revalidate time and bay before saving so a taken slot is never booked twice."""
        if not slot_is_future(values["date"], values["time"]):
            raise ValueError("This reservation time has already passed. Please select a future time slot.")
        if not self.bay_available(values["bay"], values["date"], values["time"]):
            raise ValueError(f"{values['bay']} is no longer available for this date and time. Please choose another bay.")
        reservation_id = values.get("reservation_id") or self.next_reservation_id()
        if any(r["reservation_id"] == reservation_id for r in self.data["reservations"]):
            raise ValueError("This reservation already exists. Please submit your request again.")
        self.data["reservations"].append({
            "reservation_id": reservation_id,
            "username": values["username"],
            "customer": values["customer"],
            "contact": values["contact"],
            "vehicle": values["vehicle"],
            "service": values["service"],
            "booking_date": values["date"],
            "booking_time": values["time"],
            "bay": values["bay"],
            "total": values["total"],
            "status": "Pending",
            "created_at": business_now().isoformat(timespec="seconds"),
            "reviewed_at": None,
            "reviewed_by": None,
        })
        self.save()
        return reservation_id

    def set_booking_status(self, reservation_id, status, admin):
        for record in self.data["reservations"]:
            if record["reservation_id"] == reservation_id:
                record["status"] = status
                record["reviewed_at"] = business_now().isoformat(timespec="seconds")
                record["reviewed_by"] = admin
                break
        self.save()
        if status == "Rejected":
            self.ensure_refund_request(reservation_id)

    def add_payment(self, reservation_id, method, due, amount, reference=None, reference_image=None,
                    payment_option=None):
        """Store a submitted payment as unverified; only an admin can confirm it."""
        if not reference_image:
            raise ValueError("Please upload a payment reference image before submitting.")
        ok, message = validate_payment_image(reference_image)
        if not ok:
            raise ValueError(message)
        reservation = self.get_reservation(reservation_id)
        if not reservation:
            raise ValueError("That reservation could not be found.")
        eligibility = self.payment_eligibility(reservation_id)
        if not eligibility or eligibility["outstanding"] <= 0:
            raise ValueError("This reservation is already fully paid. No further payment can be submitted.")
        try:
            amount = round(float(amount), 2)
        except (TypeError, ValueError):
            raise ValueError("Enter a valid numeric payment amount.")
        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero.")
        if amount > eligibility["outstanding"] + 0.005:
            raise ValueError(
                f"Payment cannot exceed the outstanding balance of "
                f"{money(eligibility['outstanding'])}."
            )
        if payment_option:
            option = str(payment_option).strip().lower()
            if "downpayment" in option or "30%" in option:
                if not eligibility["downpayment_available"]:
                    raise ValueError(eligibility["downpayment_message"] or DOWNPAYMENT_COMPLETED_MESSAGE)
                expected = round(max(0.0, float(eligibility.get("downpayment") or 0) - float(eligibility.get("confirmed") or 0)), 2)
                if abs(amount - expected) > 0.005:
                    raise ValueError(f"The amount for Downpayment (30%) must be {money(expected)}.")
                if amount > expected + 0.005 or amount > float(eligibility["outstanding"]) + 0.005:
                    raise ValueError("The submitted amount exceeds the required amount for the selected payment option.")
            elif "full" in option:
                if not eligibility["full_available"]:
                    raise ValueError(eligibility["full_message"] or "The Full Payment option is no longer available.")
                expected = round(float(eligibility["outstanding"]), 2)
                if abs(amount - expected) > 0.005:
                    raise ValueError(f"The amount for Full Payment must be {money(expected)}.")
            else:
                raise ValueError("Please select a valid payment option.")
        if not reference:
            reference = f"IMG-{business_now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}"
        if self.reference_taken(method, reference):
            raise ValueError("A payment with this reference number was already recorded. Duplicate transactions are not allowed.")
        next_id = 1
        for record in self.data["payments"]:
            try:
                next_id = max(next_id, int(record["payment_id"]) + 1)
            except (KeyError, TypeError, ValueError):
                continue
        saved_image = self._store_payment_image(reference_image, next_id, reservation_id)
        self.data["payments"].append({
            "payment_id": next_id,
            "reservation_id": reservation_id,
            "method": method,
            "downpayment_due": eligibility["downpayment"],
            "amount_submitted": amount,
            "reference": reference,
            "reference_image": saved_image,
            "reference_image_name": Path(reference_image).name,
            "verification_status": "Unverified",
            "submitted_at": business_now().isoformat(timespec="seconds"),
            "verified_at": None,
            "verified_by": None,
            "payment_option": payment_option,
        })
        self.save()
        return next_id

    def _store_payment_image(self, source_path, payment_id, reservation_id):
        """Copy the uploaded image into the app data folder so it survives logouts and restarts."""
        source = Path(source_path)
        suffix = source.suffix.lower()
        stamp = business_now().strftime("%Y%m%d%H%M%S")
        target_name = f"PAY-{int(payment_id):03d}-{reservation_id}-{stamp}-{secrets.token_hex(3)}{suffix}"
        target = PAYMENT_IMAGE_DIR / target_name
        try:
            shutil.copyfile(source, target)
        except OSError as exc:
            raise ValueError(f"The payment reference image could not be saved: {exc}") from exc
        try:
            return target.relative_to(APP_DIR).as_posix()
        except ValueError:
            return str(target)

    def payment_image_path(self, record):
        """Resolve the stored image path for a payment record, or None when unavailable."""
        if not isinstance(record, dict):
            return None
        value = record.get("reference_image")
        if not value:
            return None
        path = Path(value)
        if not path.is_absolute():
            path = APP_DIR / path
        return path if path.is_file() else None

    def reference_taken(self, method, reference, exclude_payment_id=None):
        """A transaction reference may only be recorded once per payment method."""
        needle = str(reference).strip().lower()
        if not needle:
            return False
        for record in self.data["payments"]:
            if exclude_payment_id is not None and str(record.get("payment_id")) == str(exclude_payment_id):
                continue
            same_method = str(record.get("method") or "").strip().lower() == str(method).strip().lower()
            same_reference = str(record.get("reference") or "").strip().lower() == needle
            if same_method and same_reference:
                return True
        return False

    def payment_status(self, reservation_id):
        """Return (status label, confirmed paid, awaiting verification, remaining balance)."""
        record = self.get_reservation(reservation_id)
        total = float(record["total"]) if record else 0.0
        confirmed = round(self._verified_total(reservation_id), 2)
        pending = round(self._pending_total(reservation_id), 2)
        remaining = round(max(0.0, total - confirmed), 2)
        return payment_status_label(total, confirmed, pending), confirmed, pending, remaining

    def available_to_pay(self, reservation_id):
        """Amount the customer may still submit (total minus already confirmed payments)."""
        record = self.get_reservation(reservation_id)
        total = float(record["total"]) if record else 0.0
        confirmed = self._verified_total(reservation_id)
        return round(max(0.0, total - confirmed), 2)

    def payment_eligibility(self, reservation_id):
        """Return confirmed balances and the payment options currently allowed."""
        record = self.get_reservation(reservation_id)
        if not record:
            return None
        total = round(float(record.get("total") or 0), 2)
        downpayment = round(total * DOWNPAYMENT_RATE, 2)
        confirmed = round(self._verified_total(reservation_id), 2)
        pending = round(self._pending_total(reservation_id), 2)
        outstanding = round(max(0.0, total - confirmed), 2)
        downpayment_remaining = round(max(0.0, downpayment - confirmed), 2)
        downpayment_available = outstanding > 0.005 and downpayment_remaining > 0.005
        full_available = outstanding > 0.005
        downpayment_exceeded = confirmed > downpayment + 0.005
        downpayment_completed = abs(confirmed - downpayment) <= 0.005
        if downpayment_exceeded:
            downpayment_state = "exceeded"
            downpayment_message = DOWNPAYMENT_EXCEEDED_MESSAGE
        elif downpayment_completed:
            downpayment_state = "completed"
            downpayment_message = DOWNPAYMENT_COMPLETED_MESSAGE
        elif not downpayment_available:
            downpayment_state = "unavailable"
            downpayment_message = ("The 30% payment option is unavailable for this reservation.")
        else:
            downpayment_state = "available"
            downpayment_message = ""
        full_message = ("The Full Payment option is unavailable because the outstanding balance is zero.")
        return {
            "total": total,
            "downpayment": downpayment,
            "downpayment_remaining": downpayment_remaining,
            "confirmed": confirmed,
            "pending": pending,
            "outstanding": outstanding,
            "downpayment_available": downpayment_available,
            "full_available": full_available,
            "downpayment_state": downpayment_state,
            "downpayment_exceeded": downpayment_exceeded,
            "downpayment_completed": downpayment_completed,
            "downpayment_message": downpayment_message,
            "full_message": full_message,
        }

    def payments_for_reservation(self, reservation_id):
        rows = [p for p in self.data["payments"] if p["reservation_id"] == reservation_id]
        rows.sort(key=lambda p: int(p["payment_id"]), reverse=True)
        return [dict(p) for p in rows]

    def latest_payment(self, reservation_id):
        payments = self.payments_for_reservation(reservation_id)
        return payments[0] if payments else None

    def next_refund_id(self):
        numbers = []
        for record in self.data["refunds"]:
            suffix = str(record.get("refund_id") or "").split("-")[-1]
            if suffix.isdigit():
                numbers.append(int(suffix))
        return f"REF-{(max(numbers) if numbers else 0) + 1:04d}"

    def _refund_record(self, refund_id):
        for record in self.data["refunds"]:
            if str(record.get("refund_id")) == str(refund_id):
                return record
        return None

    def refunds_for_reservation(self, reservation_id):
        rows = [dict(r) for r in self.data["refunds"] if r.get("reservation_id") == reservation_id]
        rows.sort(key=lambda r: str(r.get("refund_id") or ""))
        return rows

    def refund_for_reservation(self, reservation_id):
        refunds = self.refunds_for_reservation(reservation_id)
        return refunds[-1] if refunds else None

    def refunds_for_user(self, username):
        rows = [dict(r) for r in self.data["refunds"] if r.get("username") == username]
        rows.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("refund_id") or "")),
                  reverse=True)
        return rows

    def ensure_refund_request(self, reservation_id):
        """Create one pending refund request for a rejected booking's confirmed payments."""
        reservation = self.get_reservation(reservation_id)
        if not reservation or reservation.get("status") != "Rejected":
            return None
        verified = [p for p in self.data["payments"]
                    if p.get("reservation_id") == reservation_id
                    and p.get("verification_status") == "Verified"]
        confirmed = round(sum(float(p.get("amount_submitted") or 0) for p in verified), 2)
        existing = self.refund_for_reservation(reservation_id)
        if existing:
            record = self._refund_record(existing.get("refund_id"))
            if not record:
                return None
            if record.get("status") in ("Pending", "Processing"):
                other_refunds = sum(
                    float(ref.get("amount") or 0) for ref in self.data["refunds"]
                    if ref.get("reservation_id") == reservation_id
                    and str(ref.get("refund_id")) != str(record.get("refund_id"))
                    and ref.get("status") != "Cancelled"
                )
                refundable = round(max(0.0, confirmed - other_refunds), 2)
                payment_ids = sorted({int(p["payment_id"]) for p in verified})
                payment_methods = sorted({str(p.get("method") or "") for p in verified
                                          if p.get("method")})
                changed = False
                if refundable > float(record.get("amount") or 0) + 0.005:
                    record["amount"] = refundable
                    changed = True
                if record.get("payment_ids") != payment_ids:
                    record["payment_ids"] = payment_ids
                    changed = True
                if record.get("payment_methods") != payment_methods:
                    record["payment_methods"] = payment_methods
                    changed = True
                if abs(float(record.get("confirmed_paid") or 0) - confirmed) > 0.005:
                    record["confirmed_paid"] = confirmed
                    changed = True
                if changed:
                    record["updated_at"] = business_now().isoformat(timespec="seconds")
                    self.save()
            return dict(record)
        if confirmed <= 0.005:
            return None
        other_refunds = sum(
            float(ref.get("amount") or 0) for ref in self.data["refunds"]
            if ref.get("reservation_id") == reservation_id
            and ref.get("status") != "Cancelled"
        )
        amount = round(max(0.0, confirmed - other_refunds), 2)
        if amount <= 0.005:
            return None
        now = business_now().isoformat(timespec="seconds")
        customer = self.user(reservation.get("username")) or {}
        record = {
            "refund_id": self.next_refund_id(),
            "reservation_id": reservation_id,
            "username": reservation.get("username"),
            "amount": amount,
            "confirmed_paid": confirmed,
            "payment_ids": sorted({int(p["payment_id"]) for p in verified}),
            "payment_methods": sorted({str(p.get("method") or "") for p in verified
                                       if p.get("method")}),
            "refund_method": customer.get("refund_method") or "",
            "account_holder": customer.get("refund_account_name") or "",
            "account_number": customer.get("refund_account_number") or "",
            "bank_name": customer.get("refund_bank_name") or "",
            "status": "Pending",
            "reference": "",
            "refund_date": "",
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "processed_by": None,
        }
        self.data["refunds"].append(record)
        self.save()
        return dict(record)

    def get_refund(self, refund_id):
        record = self._refund_record(refund_id)
        return dict(record) if record else None

    def update_refund_details(self, reservation_id, username, method, holder, account_number,
                              bank_name=""):
        """Save the authenticated customer's refund destination for their rejected booking."""
        reservation = self.get_reservation(reservation_id)
        if not reservation or reservation.get("username") != username:
            return False, "That reservation could not be found."
        if reservation.get("status") != "Rejected":
            return False, "Refund details can only be provided for rejected bookings."
        refund = self.refund_for_reservation(reservation_id)
        if not refund:
            refund = self.ensure_refund_request(reservation_id)
        if not refund:
            return False, "No confirmed payment is available to refund for this booking."
        if refund.get("status") == "Completed":
            return False, "This refund has already been completed and can no longer be changed."
        method = str(method or "").strip()
        holder = " ".join(str(holder or "").split())
        account_number = str(account_number or "").strip()
        bank_name = " ".join(str(bank_name or "").split()) if method == "Bank Transfer" else ""
        message = refund_account_error(method, holder, account_number, bank_name)
        if message:
            return False, message
        record = self._refund_record(refund.get("refund_id"))
        if not record:
            return False, "The refund request could not be found."
        record["refund_method"] = method
        record["account_holder"] = holder
        record["account_number"] = account_number
        record["bank_name"] = bank_name
        record["updated_at"] = business_now().isoformat(timespec="seconds")
        for user_record in self.data["users"]:
            if user_record.get("username") == username:
                user_record["refund_method"] = method
                user_record["refund_account_name"] = holder
                user_record["refund_account_number"] = account_number
                user_record["refund_bank_name"] = bank_name
                break
        self.save()
        return True, "Your refund details have been saved."

    def update_refund_status(self, refund_id, status, admin, amount=None, refund_date=None,
                             reference=None):
        """Record an admin-processed refund and notify the customer when completed."""
        account = self.user(admin)
        if not account or account.get("role") != "admin":
            return False, "Only an authorized admin can update a refund."
        record = self._refund_record(refund_id)
        if not record:
            return False, "That refund request could not be found."
        status = str(status or "").strip()
        if status not in REFUND_STATUSES:
            return False, "Please select a valid refund status."
        if record.get("status") == "Completed":
            return False, "This refund has already been completed."
        method = record.get("refund_method") or ""
        holder = record.get("account_holder") or ""
        account_number = record.get("account_number") or ""
        bank_name = record.get("bank_name") or ""
        if status in ("Processing", "Completed"):
            if not refund_details_complete(method, holder, account_number, bank_name):
                return False, "The customer has not submitted complete refund account details yet."
        now = business_now().isoformat(timespec="seconds")
        reservation_id = record.get("reservation_id")
        verified = [p for p in self.data["payments"]
                    if p.get("reservation_id") == reservation_id
                    and p.get("verification_status") == "Verified"]
        confirmed = round(sum(float(p.get("amount_submitted") or 0) for p in verified), 2)
        other_completed = sum(
            float(ref.get("amount") or 0) for ref in self.data["refunds"]
            if ref.get("reservation_id") == reservation_id
            and str(ref.get("refund_id")) != str(record.get("refund_id"))
            and ref.get("status") == "Completed"
        )
        refundable = round(max(0.0, confirmed - other_completed), 2)
        if refundable <= 0.005 and status in ("Processing", "Completed"):
            return False, "No confirmed payment amount remains to refund."

        supplied_amount = str(amount).strip() if amount is not None else ""
        if supplied_amount:
            try:
                refund_amount = round(float(supplied_amount), 2)
            except (TypeError, ValueError):
                return False, "Enter a valid refund amount."
            if refund_amount <= 0:
                return False, "The refund amount must be greater than zero."
            if refund_amount > refundable + 0.005:
                return False, f"The refund amount cannot exceed the refundable balance of {money(refundable)}."
            record["amount"] = refund_amount

        supplied_date = str(refund_date).strip() if refund_date is not None else ""
        if supplied_date:
            normalized_date = normalize_refund_date(supplied_date)
            if normalized_date is None:
                return False, "Enter the refund date as MM/DD/YYYY."
            record["refund_date"] = normalized_date
        elif status == "Completed" and not record.get("refund_date"):
            record["refund_date"] = business_now().date().isoformat()

        if reference is not None:
            record["reference"] = str(reference).strip()
        if status == "Completed":
            record["confirmed_paid"] = confirmed
            record["payment_ids"] = sorted({int(p["payment_id"]) for p in verified})
            record["payment_methods"] = sorted({str(p.get("method") or "") for p in verified
                                                if p.get("method")})
            record["completed_at"] = now
        record["status"] = status
        record["processed_by"] = admin
        record["updated_at"] = now
        self.save()
        if status == "Completed":
            reference_text = record.get("reference") or "No reference provided"
            self.add_notification(
                record.get("username"),
                "Refund Completed",
                (f"Your refund of {money(record.get('amount') or 0)} for reservation "
                 f"{reservation_id} has been completed. Reference: {reference_text}."),
                related_type="refund",
                related_id=record.get("refund_id"),
            )
        return True, f"Refund {refund_id} status set to {status}."

    def verify_payment(self, payment_id, status, admin):
        """Only an authorized administrator may confirm, reverse, or reject a payment."""
        account = self.user(admin)
        if not account or account.get("role") != "admin":
            return False, "Only an authorized admin can verify a payment."
        target = None
        for record in self.data["payments"]:
            if str(record["payment_id"]) == str(payment_id):
                target = record
                break
        if target is None:
            return False, "That payment record could not be found."
        if status == "Verified":
            reservation = self.get_reservation(target["reservation_id"])
            total = float(reservation["total"]) if reservation else 0.0
            other_paid = sum(float(p["amount_submitted"]) for p in self.data["payments"]
                             if p["reservation_id"] == target["reservation_id"]
                             and str(p["payment_id"]) != str(payment_id)
                             and p["verification_status"] == "Verified")
            if other_paid + float(target["amount_submitted"]) > total + 0.005:
                return False, "Verifying this payment would exceed the total reservation amount."
        target["verification_status"] = status
        target["verified_at"] = business_now().isoformat(timespec="seconds")
        target["verified_by"] = admin
        if status != "Verified":
            target["approval_status"] = None
            target["approved_at"] = None
            target["approved_by"] = None
        self.save()
        if status == "Verified":
            reservation = self.get_reservation(target["reservation_id"])
            if reservation and reservation.get("status") == "Rejected":
                self.ensure_refund_request(target["reservation_id"])
        return True, f"Payment {payment_id} status set to {status}."

    def approve_payment(self, payment_id, admin):
        """Approve a payment; only a verified payment can be approved."""
        account = self.user(admin)
        if not account or account.get("role") != "admin":
            return False, "Only an authorized admin can approve a payment."
        target = None
        for record in self.data["payments"]:
            if str(record["payment_id"]) == str(payment_id):
                target = record
                break
        if target is None:
            return False, "That payment record could not be found."
        if target.get("verification_status") != "Verified":
            return False, "Only a verified payment can be approved. Verify the payment first."
        if target.get("approval_status") == "Approved":
            return False, f"Payment {payment_id} is already approved."
        target["approval_status"] = "Approved"
        target["approved_at"] = business_now().isoformat(timespec="seconds")
        target["approved_by"] = admin
        self.save()
        return True, f"Payment {payment_id} approved."

    def payment_summary(self):
        """Summarize collected, awaiting verification, and outstanding amounts."""
        by_method = {method: {"count": 0, "verified": 0.0, "pending": 0.0} for method in PAYMENT_METHODS}
        collected = 0.0
        pending_amount = 0.0
        verified_count = 0
        pending_count = 0
        for record in self.data["payments"]:
            amount = float(record.get("amount_submitted") or 0)
            method = str(record.get("method") or "")
            entry = by_method.setdefault(method, {"count": 0, "verified": 0.0, "pending": 0.0})
            entry["count"] += 1
            if record.get("verification_status") == "Verified":
                collected += amount
                verified_count += 1
                entry["verified"] += amount
            elif record.get("verification_status") == "Unverified":
                pending_amount += amount
                pending_count += 1
                entry["pending"] += amount
        billed = sum(float(r["total"]) for r in self.data["reservations"]
                     if r["status"] not in ("Cancelled", "Rejected"))
        return {
            "total_collected": round(collected, 2),
            "pending_amount": round(pending_amount, 2),
            "verified_count": verified_count,
            "pending_count": pending_count,
            "outstanding": round(max(0.0, billed - collected), 2),
            "by_method": by_method,
        }

    def sales_summary(self):
        approved_value = sum(float(r["total"]) for r in self.data["reservations"]
                              if r["status"] in ("Approved", "Completed"))
        completed_value = sum(float(r["total"]) for r in self.data["reservations"]
                              if r["status"] == "Completed")
        paid = sum(float(p["amount_submitted"]) for p in self.data["payments"]
                   if p["verification_status"] == "Verified")
        return approved_value, completed_value, paid

    def counts(self):
        data = {}
        for record in self.data["reservations"]:
            data[record["status"]] = data.get(record["status"], 0) + 1
        return {
            "total": sum(data.values()), "pending": data.get("Pending", 0),
            "approved": data.get("Approved", 0), "rejected": data.get("Rejected", 0),
            "completed": data.get("Completed", 0)
        }

    def _newest_first(self, rows):
        """Order records newest first (same ordering the old query used)."""
        return sorted(rows, key=lambda r: (str(r.get("created_at") or ""),
                                           str(r.get("reservation_id") or "")), reverse=True)

    def _verified_total(self, reservation_id):
        return sum(float(p["amount_submitted"]) for p in self.data["payments"]
                   if p["reservation_id"] == reservation_id and p["verification_status"] == "Verified")

    def _pending_total(self, reservation_id):
        return sum(float(p["amount_submitted"]) for p in self.data["payments"]
                   if p["reservation_id"] == reservation_id and p["verification_status"] == "Unverified")

    def close(self):
        self.save()


class WashApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WASHAPP - Smart Carwash Reservation System")
        self.geometry("1000x650")
        self.minsize(700, 480)
        self.configure(bg=COLORS["bg"])

        self._scroll_container = tk.Frame(self, bg=COLORS["bg"])
        self._scroll_container.pack(fill="both", expand=True)
        self._page_canvas = tk.Canvas(
            self._scroll_container, bg=COLORS["bg"], highlightthickness=0, borderwidth=0
        )
        self._page_scrollbar = ttk.Scrollbar(
            self._scroll_container, orient="vertical", command=self._page_canvas.yview
        )
        self._page_canvas.configure(yscrollcommand=self._page_scrollbar.set)
        self._page_scrollbar.pack(side="right", fill="y")
        self._page_canvas.pack(side="left", fill="both", expand=True)
        self.page = tk.Frame(self._page_canvas, bg=COLORS["bg"])
        self._page_window = self._page_canvas.create_window(
            (0, 0), window=self.page, anchor="nw"
        )
        self.page.bind("<Configure>", self._update_scroll_region)
        self._page_canvas.bind("<Configure>", self._resize_scroll_page)
        self._page_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self._page_canvas.bind_all("<Button-4>", self._on_mousewheel_linux)
        self._page_canvas.bind_all("<Button-5>", self._on_mousewheel_linux)

        self.store = Store()
        self.current_user = None
        self.selected_vehicle = "Sedan"
        self.selected_reservation_id = None
        self.setup_styles()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show_landing()

    def _update_scroll_region(self, _event=None):
        self._page_canvas.configure(scrollregion=self._page_canvas.bbox("all"))

    def _resize_scroll_page(self, event):

        self._page_canvas.itemconfigure(self._page_window, width=event.width)

    def _on_mousewheel(self, event):
        if getattr(event, "delta", 0):
            self._page_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _on_mousewheel_linux(self, event):
        if event.num == 4:
            self._page_canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self._page_canvas.yview_scroll(1, "units")

    def setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TCombobox", padding=7, fieldbackground="white", background="white", foreground="black")
        style.configure("Treeview", background=COLORS["card"], foreground="white", fieldbackground=COLORS["card"], rowheight=28)
        style.configure("Treeview.Heading", background="#173247", foreground="white", font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", COLORS["button"])], foreground=[("selected", "white")])

    def clear(self):
        job = getattr(self, "_admin_refresh_job", None)
        if job:
            try:
                self.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
            self._admin_refresh_job = None
        self._admin_view_active = False
        for widget in self.page.winfo_children():
            widget.destroy()
        self.page.update_idletasks()
        self._page_canvas.yview_moveto(0)

    def header(self, title, subtitle=""):
        frame = tk.Frame(self.page, bg=COLORS["bg"])
        frame.pack(fill="x", padx=22, pady=(10, 5))
        tk.Label(frame, text="WASHAPP", font=("Segoe UI", 22, "bold"), fg=COLORS["cyan"], bg=COLORS["bg"]).pack(anchor="w")
        tk.Label(frame, text=title, font=("Segoe UI", 15, "bold"), fg="white", bg=COLORS["bg"]).pack(anchor="w")
        if subtitle:
            tk.Label(frame, text=subtitle, font=("Segoe UI", 9), fg="#d9f7ff", bg=COLORS["bg"]).pack(anchor="w")

    def card(self, parent, **kwargs):
        return tk.Frame(parent, bg=COLORS["card"], highlightbackground="#23374e", highlightthickness=1, **kwargs)

    def btn(self, parent, label, command, primary=True, **kwargs):
        return tk.Button(parent, text=label, command=command, font=("Segoe UI", 9, "bold"),
                         fg="white", bg=COLORS["button"] if primary else COLORS["button2"],
                         activebackground=COLORS["cyan"], activeforeground="white",
                         relief="flat", bd=0, cursor="hand2", padx=12, pady=9, **kwargs)

    def label(self, parent, text, size=10, color="white", bold=False, **kwargs):
        return tk.Label(parent, text=text, font=("Segoe UI", size, "bold" if bold else "normal"),
                        fg=color, bg=kwargs.pop("bg", COLORS["card"]), **kwargs)

    def show_landing(self):
        self.current_user = None
        self.clear()
        self.header("Smart Carwash Reservation System", "Keeps Your Ride Shining.")
        body = tk.Frame(self.page, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=22, pady=(0, 8))

        self.label(body, "SELECT YOUR VEHICLE", 19, COLORS["white"], True, bg=COLORS["bg"]).pack(pady=(8, 3))
        self.label(body, "Choose your vehicle type to continue.", 10, COLORS["cyan"], True, bg=COLORS["bg"]).pack(pady=(0, 12))

        vehicle_row = tk.Frame(body, bg=COLORS["bg"])
        vehicle_row.pack()
        vehicle_icons = {"Sedan": "🚘", "SUV": "🚙", "Van": "🚐", "Pick-up": "🛻", "Motorcycle": "🏍"}
        for vehicle in VEHICLES:
            card = self.card(vehicle_row, width=125, height=150)
            card.pack(side="left", padx=5)
            card.pack_propagate(False)
            self.label(card, vehicle_icons.get(vehicle, "🚗"), 28, COLORS["cyan"]).pack(pady=(10, 5))
            self.label(card, vehicle, 11, COLORS["white"], True).pack(pady=(0, 6))
            self.btn(card, "SELECT", lambda v=vehicle: self.select_landing_vehicle(v), width=9).pack()

        self.landing_vehicle = tk.StringVar(value="")
        self.landing_service = tk.StringVar(value="")
        selector = self.card(body)
        selector.pack(fill="x", padx=45, pady=(14, 5))
        self.label(selector, "SERVICE AND PRICE", 13, COLORS["cyan"], True).pack(pady=(9, 6))
        controls = tk.Frame(selector, bg=COLORS["card"])
        controls.pack(padx=12, pady=(0, 8))
        self.label(controls, "Vehicle", 10, bold=True).grid(row=0, column=0, padx=8, pady=5)
        self.landing_vehicle_display = ttk.Combobox(controls, textvariable=self.landing_vehicle, values=VEHICLES, state="readonly", width=15)
        self.landing_vehicle_display.grid(row=0, column=1, padx=8, pady=5)
        self.landing_vehicle_display.bind("<<ComboboxSelected>>", lambda e: self.refresh_landing_prices())
        self.label(controls, "Service", 10, bold=True).grid(row=0, column=2, padx=8, pady=5)
        self.landing_service_combo = ttk.Combobox(controls, textvariable=self.landing_service, values=[], state="disabled", width=28)
        self.landing_service_combo.grid(row=0, column=3, padx=8, pady=5)
        self.landing_service_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_landing_prices())
        self.btn(body, "CONFIRM AND CONTINUE", self.confirm_landing_selection, width=27).pack(pady=(8, 3))
        self.label(body, "After confirming, choose to log in or create a customer account.", 9, COLORS["muted"], bg=COLORS["bg"]).pack(pady=(2, 0))

        self.btn(body, "ADMIN ACCOUNT", self.show_admin_login, primary=False, width=20).pack(pady=(9, 3))

    def select_landing_vehicle(self, vehicle):
        self.landing_vehicle.set(vehicle)
        self.refresh_landing_prices()

    def refresh_landing_prices(self):
        vehicle = self.landing_vehicle.get()
        if not vehicle:
            self.landing_service_combo.configure(state="disabled", values=[])
            return
        options = service_options(vehicle)
        current_service = service_name(self.landing_service.get()) if self.landing_service.get() else SERVICES[0]
        self.landing_service_combo.configure(state="readonly", values=options)
        if current_service not in SERVICES:
            current_service = SERVICES[0]
        selected_label = f"{current_service} — {money(PRICES[current_service][vehicle])}"
        self.landing_service.set(selected_label)

    def confirm_landing_selection(self):
        vehicle = self.landing_vehicle.get()
        service = service_name(self.landing_service.get())
        if not vehicle:
            messagebox.showwarning("Select Vehicle", "Please select a vehicle first.")
            return
        if service not in SERVICES:
            messagebox.showwarning("Select Service", "Please select a carwash service.")
            return
        self.selected_vehicle = vehicle
        self.landing_selected_service = service
        self.show_continue_choice()

    def show_continue_choice(self):
        self.clear()
        self.header("Ready to Continue?", "Your vehicle and service selection are ready.")
        box = self.card(self.page)
        box.pack(fill="x", padx=260, pady=35)
        self.label(box, "YOUR SELECTION", 15, COLORS["cyan"], True).pack(pady=(25, 14))
        self.label(box, f"Vehicle: {self.selected_vehicle}", 12, bold=True).pack(pady=5)
        service = getattr(self, "landing_selected_service", SERVICES[0])
        self.label(box, f"Service: {service}", 12, bold=True).pack(pady=5)
        self.label(box, f"Price: {money(PRICES[service][self.selected_vehicle])}", 14, COLORS["cyan"], True).pack(pady=8)
        self.label(box, "Log in to an existing account or register as a new customer.", 10, COLORS["muted"]).pack(pady=(4, 16))
        self.btn(box, "LOGIN", self.show_login, width=20).pack(pady=6)
        self.btn(box, "CREATE CUSTOMER ACCOUNT", self.show_register, primary=False, width=25).pack(pady=6)
        self.btn(box, "BACK TO VEHICLE SELECTION", self.show_landing, primary=False).pack(pady=(12, 24))

    def show_login(self):
        self.clear()
        self.header("Login", "Sign in to access customer reservations or administration.")
        box = self.card(self.page)
        box.pack(fill="x", padx=250, pady=25)
        self.label(box, "USERNAME", 10, COLORS["cyan"], True).pack(anchor="w", padx=30, pady=(25, 5))
        username = tk.Entry(box, font=("Segoe UI", 11), relief="flat")
        username.pack(fill="x", padx=30, ipady=8)
        self.label(box, "PASSWORD", 10, COLORS["cyan"], True).pack(anchor="w", padx=30, pady=(15, 5))
        password = tk.Entry(box, show="*", font=("Segoe UI", 11), relief="flat")
        password.pack(fill="x", padx=30, ipady=8)
        def login():
            name, pwd = username.get().strip(), password.get()
            if not name or not pwd:
                messagebox.showwarning("Missing Information", "Enter both username and password.")
                return
            user = self.store.user(name)
            if not user or not verify_password(pwd, user["password_hash"]):
                messagebox.showerror("Login Failed", "Invalid username or password.")
                return
            if user["password_hash"] == pwd:
                self.store.migrate_legacy_password(name, pwd)
                user = self.store.user(name)
            self.current_user = dict(user)
            if user["role"] == "admin":
                self.show_admin_dashboard()
            else:
                self.show_customer_dashboard()
        self.btn(box, "LOGIN", login, width=15).pack(pady=15)
        self.btn(box, "BACK TO LANDING PAGE", self.show_landing, primary=False).pack(pady=(0, 25))

    def show_admin_login(self):
        """Display a dedicated login page that accepts administrator accounts only."""
        self.clear()
        self.header("Admin Login", "Authorized WASHAPP administrators only.")
        box = self.card(self.page)
        box.pack(fill="x", padx=250, pady=35)
        self.label(box, "ADMINISTRATOR SIGN IN", 15, COLORS["cyan"], True).pack(pady=(25, 15))
        self.label(box, "USERNAME", 10, COLORS["cyan"], True).pack(anchor="w", padx=10, pady=(5, 5))
        username = tk.Entry(box, font=("Segoe UI", 11), relief="flat")
        username.pack(fill="x", padx=30, ipady=8)
        self.label(box, "PASSWORD", 10, COLORS["cyan"], True).pack(anchor="w", padx=10, pady=(5, 5))
        password = tk.Entry(box, show="*", font=("Segoe UI", 11), relief="flat")
        password.pack(fill="x", padx=30, ipady=8)

        def login_admin():
            name, pwd = username.get().strip(), password.get()
            if not name or not pwd:
                messagebox.showwarning("Missing Information", "Enter both admin username and password.")
                return
            user = self.store.user(name)
            if not user or not verify_password(pwd, user["password_hash"]):
                messagebox.showerror("Login Failed", "Invalid admin username or password.")
                return
            if user["password_hash"] == pwd:
                self.store.migrate_legacy_password(name, pwd)
                user = self.store.user(name)
            if user["role"] != "admin":
                messagebox.showerror("Access Denied", "This page is for admin accounts only.")
                return
            self.current_user = dict(user)
            self.show_admin_dashboard()

        self.btn(box, "ADMIN LOGIN", login_admin, width=20).pack(pady=20)
        self.btn(box, "BACK TO LANDING PAGE", self.show_landing, primary=False).pack(pady=(0, 25))

    def show_register(self):
        self.clear()
        self.header("Customer Registration", "Create an account and save where refunds should be sent.")
        box = self.card(self.page)
        box.pack(fill="x", padx=250, pady=10)
        fields = {}
        for name, secret in [("Full Name", False), ("Username", False), ("Password", True), ("Confirm Password", True), ("Contact Number", False)]:
            self.label(box, name, 10, COLORS["cyan"], True).pack(anchor="w", padx=30, pady=(10, 3))
            entry = tk.Entry(box, show="*" if secret else "", font=("Segoe UI", 11), relief="flat")
            entry.pack(fill="x", padx=30, ipady=7)
            fields[name] = entry

        self.label(box, "PAYMENT AND REFUND DETAILS", 12, COLORS["cyan"], True).pack(
            anchor="w", padx=30, pady=(18, 2))
        self.label(box, "Required. Refunds are sent only to this verified account.",
                   9, COLORS["muted"]).pack(anchor="w", padx=30, pady=(0, 4))
        refund_method = tk.StringVar(value="GCash")
        self.label(box, "Refund Method", 10, COLORS["cyan"], True).pack(
            anchor="w", padx=30, pady=(8, 3))
        ttk.Combobox(box, textvariable=refund_method, values=REFUND_METHODS,
                     state="readonly").pack(fill="x", padx=30)
        self.label(box, "Account Holder Name", 10, COLORS["cyan"], True).pack(
            anchor="w", padx=30, pady=(10, 3))
        refund_holder = tk.Entry(box, font=("Segoe UI", 11), relief="flat")
        refund_holder.pack(fill="x", padx=30, ipady=7)
        bank_frame = tk.Frame(box, bg=COLORS["card"])
        self.label(bank_frame, "Bank Name", 10, COLORS["cyan"], True).pack(
            anchor="w", pady=(10, 3))
        refund_bank = tk.Entry(bank_frame, font=("Segoe UI", 11), relief="flat")
        refund_bank.pack(fill="x", ipady=7)
        account_frame = tk.Frame(box, bg=COLORS["card"])
        account_frame.pack(fill="x", padx=30)
        refund_number_label = self.label(account_frame, "GCash Mobile Number",
                                         10, COLORS["cyan"], True)
        refund_number_label.pack(anchor="w", pady=(10, 3))
        refund_number = tk.Entry(account_frame, font=("Segoe UI", 11), relief="flat")
        refund_number.pack(fill="x", ipady=7)

        def refresh_refund_fields(*_):
            if refund_method.get() == "Bank Transfer":
                bank_frame.pack(fill="x", padx=30, before=account_frame)
                refund_number_label.config(text="Bank Account Number")
            else:
                bank_frame.pack_forget()
                refund_number_label.config(text="GCash Mobile Number")
        refund_method.trace_add("write", refresh_refund_fields)
        refresh_refund_fields()

        def register():
            full = fields["Full Name"].get().strip()
            username = fields["Username"].get().strip()
            password = fields["Password"].get()
            confirm = fields["Confirm Password"].get()
            contact = fields["Contact Number"].get().strip()
            if not all([full, username, password, confirm, contact]):
                messagebox.showwarning("Incomplete Registration", "Please fill in every field.")
                return
            if len(username) < 3 or any(ch.isspace() for ch in username):
                messagebox.showwarning("Invalid Username", "Username must be at least 3 characters and contain no spaces.")
                return
            if len(password) < 6:
                messagebox.showwarning("Weak Password", "Use a password with at least 6 characters.")
                return
            if password != confirm:
                messagebox.showerror("Registration Failed", "Passwords do not match.")
                return
            if self.store.user(username):
                messagebox.showerror("Registration Failed", "That username already exists.")
                return
            method = refund_method.get()
            holder = " ".join(refund_holder.get().split())
            number = refund_number.get().strip()
            bank = " ".join(refund_bank.get().split()) if method == "Bank Transfer" else ""
            problem = refund_account_error(method, holder, number, bank)
            if problem:
                messagebox.showwarning("Payment and Refund Details", problem)
                return
            ok, message = self.store.register(
                username, password, full, contact, method, holder, number, bank)
            if not ok:
                messagebox.showwarning("Registration Failed", message)
                return
            messagebox.showinfo("Success", "Account created. You can now log in.")
            self.show_login()
        self.btn(box, "CREATE ACCOUNT", register, width=22).pack(pady=18)
        self.btn(box, "BACK", self.show_landing, primary=False).pack(pady=(0, 20))

    def show_customer_dashboard(self):
        self.clear()
        self.header("Customer Dashboard", f"Welcome, {self.current_user['full_name']}!")
        top = tk.Frame(self.page, bg=COLORS["bg"])
        top.pack(fill="x", padx=30)
        self.btn(top, "NEW BOOKING", self.show_booking, width=18).pack(side="left", padx=4)
        self.btn(top, "REFRESH", self.show_customer_dashboard, primary=False, width=12).pack(side="left", padx=4)
        account_actions = tk.Frame(top, bg=COLORS["bg"])
        account_actions.pack(side="right", padx=4)
        self.btn(account_actions, "MY ACCOUNT", self.show_account_settings, primary=False, width=14).pack(side="top", fill="x", pady=(0, 4))
        self.btn(account_actions, "LOGOUT", self.logout, primary=False, width=14).pack(side="top", fill="x")
        rows = self.store.reservations_for_user(self.current_user["username"])
        for record in rows:
            if record.get("status") == "Rejected":
                self.store.ensure_refund_request(record["reservation_id"])
        self.notification_dashboard_section(self.page)
        self.refund_dashboard_section(
            self.page, self.store.refunds_for_user(self.current_user["username"]))
        self.label(self.page, f"MY RESERVATIONS: {len(rows)}", 12, COLORS["cyan"], True, bg=COLORS["bg"]).pack(anchor="w", padx=35, pady=(15, 5))
        table_frame = self.card(self.page)
        table_frame.pack(fill="both", expand=True, padx=30, pady=8)
        cols = ("id", "date", "time", "vehicle", "service", "total", "paid", "balance", "status", "payment")
        tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        headings = {"id":"Reservation ID","date":"Date","time":"Time","vehicle":"Vehicle","service":"Service","total":"Total","paid":"Amount Paid","balance":"Remaining Balance","status":"Booking Status","payment":"Payment Status"}
        widths = {"id":100,"date":95,"time":78,"vehicle":88,"service":118,"total":82,"paid":98,"balance":105,"status":98,"payment":105}
        for c in cols:
            tree.heading(c, text=headings[c]); tree.column(c, width=widths[c], anchor="center")

        tree.tag_configure("rejected", foreground="#ff4d4d")
        tree.tag_configure("approved", foreground="#36d98a")
        tree.tag_configure("pending", foreground="#ffd34d")
        tree.tag_configure("completed", background="#ffffff", foreground="#111111")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        tree.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 0))
        v_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        h_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        v_scroll.grid(row=0, column=1, sticky="ns", pady=(8, 0))
        h_scroll.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        for r in rows:
            pay_status, confirmed, pending, remaining = self.store.payment_status(r["reservation_id"])
            status_key = str(r["status"]).strip().lower()
            row_tag = status_key if status_key in ("rejected", "approved", "pending", "completed") else ""
            tree.insert("", "end", iid=r["reservation_id"], values=(r["reservation_id"], r["booking_date"], r["booking_time"], r["vehicle"], r["service"], money(r["total"]), money(confirmed), money(remaining), r["status"], pay_status), tags=(row_tag,) if row_tag else ())
        actions = tk.Frame(self.page, bg=COLORS["bg"])
        actions.pack(fill="x", padx=30, pady=(0, 15))
        self.btn(actions, "VIEW SELECTED / PAYMENT / RECEIPT", lambda: self.customer_reservation_action(tree), width=32).pack(side="left")
        self.label(actions, "Select a booking in the table first.", 9, COLORS["muted"], bg=COLORS["bg"]).pack(side="left", padx=12)

    def show_account_settings(self):
        """Account settings for the currently authenticated user only."""
        if not self.current_user:
            messagebox.showerror("Sign In Required", "Please log in to view account settings.")
            self.show_landing()
            return
        if self.current_user.get("role") != "customer":
            messagebox.showinfo("Account Settings", "Account settings are available from the customer dashboard.")
            return
        self.clear()
        self.header("My Account", "View your account information and securely change your password.")
        panel = self.card(self.page)
        panel.pack(fill="x", padx=30, pady=15)
        self.label(panel, "ACCOUNT SETTINGS", 13, COLORS["cyan"], True).pack(anchor="w", padx=20, pady=(18, 8))
        self.label(panel, "Your account is private. Only your own account information is shown here.", 9, COLORS["muted"]).pack(anchor="w", padx=20, pady=(0, 14))
        actions = tk.Frame(panel, bg=COLORS["card"])
        actions.pack(anchor="w", padx=20, pady=(0, 20))
        self.btn(actions, "VIEW ACCOUNT INFORMATION", self.view_account_information, width=28).pack(side="left", padx=(0, 8), pady=4)
        self.btn(actions, "PAYMENT / REFUND DETAILS", self.show_refund_profile_form, primary=False, width=25).pack(side="left", padx=8, pady=4)
        self.btn(actions, "CHANGE PASSWORD", self.show_change_password, primary=False, width=22).pack(side="left", padx=8, pady=4)
        for record in self.store.reservations_for_user(self.current_user["username"]):
            if record.get("status") == "Rejected":
                self.store.ensure_refund_request(record["reservation_id"])
        self.refund_dashboard_section(
            self.page, self.store.refunds_for_user(self.current_user["username"]))
        self.btn(self.page, "BACK TO DASHBOARD", self.show_customer_dashboard, primary=False).pack(anchor="w", padx=30, pady=(0, 18))

    def view_account_information(self):
        """Show only the current user's saved account fields; never reveal a password hash."""
        if not self.current_user:
            messagebox.showerror("Sign In Required", "Please log in first.")
            return
        user = self.store.user(self.current_user["username"])
        if not user:
            messagebox.showerror("Account Not Found", "Your account could not be found.")
            return
        dialog = tk.Toplevel(self)
        dialog.title("View Account Information")
        dialog.configure(bg=COLORS["bg"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        outer = self.card(dialog)
        outer.pack(fill="both", expand=True, padx=18, pady=18)
        self.label(outer, "ACCOUNT INFORMATION", 13, COLORS["cyan"], True).pack(anchor="w", padx=20, pady=(18, 12))
        refund_method = user.get("refund_method") or "Not set"
        refund_number = user.get("refund_account_number") or ""
        details = [
            ("Full Name", user["full_name"]),
            ("Username", user["username"]),
            ("Contact", user["contact"]),
            ("Role", user["role"].title()),
            ("Refund Method", refund_method),
            ("Account Holder", user.get("refund_account_name") or "Not set"),
        ]
        if refund_method == "Bank Transfer":
            details.append(("Bank Name", user.get("refund_bank_name") or "Not set"))
        details.append(("Refund Account", mask_account_number(refund_number) if refund_number else "Not set"))
        details.append(("Password", "••••••••"))
        for field_name, value in details:
            line = tk.Frame(outer, bg=COLORS["card"])
            line.pack(fill="x", padx=20, pady=5)
            self.label(line, f"{field_name}:", 10, COLORS["muted"], True, width=14, anchor="w").pack(side="left")
            self.label(line, str(value), 10, COLORS["white"], True, anchor="w").pack(side="left", padx=(8, 0))
            if field_name == "Password":
                self.btn(
                    line,
                    self.explain_password_visibility,
                    primary=False,
                    width=16
                ).pack(side="left", padx=(12, 0))

        controls = tk.Frame(outer, bg=COLORS["card"])
        controls.pack(anchor="w", padx=20, pady=(15, 20))
        self.btn(controls, "UPDATE REFUND DETAILS", lambda: (dialog.destroy(), self.show_refund_profile_form()), width=23).pack(side="left", padx=(0, 8))
        self.btn(controls, "CHANGE PASSWORD", lambda: (dialog.destroy(), self.show_change_password()), primary=False, width=18).pack(side="left", padx=(0, 8))
        self.btn(controls, "CLOSE", dialog.destroy, primary=False, width=10).pack(side="left")

    def show_refund_profile_form(self):
        """Let a signed-in customer update their own saved refund destination."""
        if not self.current_user:
            messagebox.showerror("Sign In Required", "Please log in first.")
            return
        user = self.store.user(self.current_user["username"])
        if not user or user.get("role") != "customer":
            messagebox.showerror("Account Not Found", "Your customer account could not be found.")
            return
        dialog = tk.Toplevel(self)
        dialog.title("Payment and Refund Details")
        dialog.configure(bg=COLORS["bg"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        panel = self.card(dialog)
        panel.pack(fill="both", expand=True, padx=18, pady=18)
        self.label(panel, "PAYMENT AND REFUND DETAILS", 14, COLORS["cyan"], True).pack(
            anchor="w", padx=22, pady=(18, 5))
        self.label(panel, "Refunds will only be sent to this verified GCash or bank account.",
                   9, COLORS["muted"]).pack(anchor="w", padx=22, pady=(0, 12))
        method = tk.StringVar(value=user.get("refund_method") or "GCash")
        self.label(panel, "Refund Method", 10, COLORS["white"], True).pack(
            anchor="w", padx=22, pady=(7, 3))
        ttk.Combobox(panel, textvariable=method, values=REFUND_METHODS,
                     state="readonly", width=34).pack(fill="x", padx=22)
        self.label(panel, "Account Holder Name", 10, COLORS["white"], True).pack(
            anchor="w", padx=22, pady=(10, 3))
        holder = tk.Entry(panel, font=("Segoe UI", 10), relief="flat", width=36)
        holder.insert(0, user.get("refund_account_name") or "")
        holder.pack(fill="x", padx=22, ipady=7)
        bank_frame = tk.Frame(panel, bg=COLORS["card"])
        self.label(bank_frame, "Bank Name", 10, COLORS["white"], True).pack(
            anchor="w", pady=(10, 3))
        bank = tk.Entry(bank_frame, font=("Segoe UI", 10), relief="flat", width=36)
        bank.insert(0, user.get("refund_bank_name") or "")
        bank.pack(fill="x", ipady=7)
        number_frame = tk.Frame(panel, bg=COLORS["card"])
        number_frame.pack(fill="x", padx=22)
        number_label = self.label(number_frame, "GCash Mobile Number",
                                  10, COLORS["white"], True)
        number_label.pack(anchor="w", pady=(10, 3))
        number = tk.Entry(number_frame, font=("Segoe UI", 10), relief="flat", width=36)
        number.insert(0, user.get("refund_account_number") or "")
        number.pack(fill="x", ipady=7)

        def refresh_method(*_):
            if method.get() == "Bank Transfer":
                bank_frame.pack(fill="x", padx=22, before=number_frame)
                number_label.config(text="Bank Account Number")
            else:
                bank_frame.pack_forget()
                number_label.config(text="GCash Mobile Number")
        method.trace_add("write", refresh_method)
        refresh_method()

        def save():
            bank_name = " ".join(bank.get().split()) if method.get() == "Bank Transfer" else ""
            ok, message = self.store.update_user_refund_details(
                user["username"], method.get(), holder.get(), number.get(), bank_name)
            if not ok:
                messagebox.showwarning("Payment and Refund Details", message, parent=dialog)
                return
            messagebox.showinfo("Saved", message, parent=dialog)
            dialog.destroy()
            self.current_user = self.store.user(user["username"])
            self.show_account_settings()

        controls = tk.Frame(panel, bg=COLORS["card"])
        controls.pack(anchor="w", padx=22, pady=(18, 20))
        self.btn(controls, "SAVE DETAILS", save, width=16).pack(side="left", padx=(0, 8))
        self.btn(controls, "CANCEL", dialog.destroy, primary=False, width=10).pack(side="left")

    def explain_password_visibility(self):
        """Explain why an existing hashed password cannot be revealed."""
        messagebox.showinfo(
            "Password Security",
            "Your current password is stored as a secure one-way hash, so the original password cannot be displayed. "
            "You can change it using CHANGE PASSWORD. In that form, use SHOW PASSWORDS to view the password you are typing.",
            parent=self
        )

    def show_change_password(self):
        """Open a password-change dialog with backend verification and secure hashing."""
        if not self.current_user:
            messagebox.showerror("Sign In Required", "Please log in first.")
            return
        username = self.current_user["username"]
        dialog = tk.Toplevel(self)
        dialog.title("Change Password")
        dialog.configure(bg=COLORS["bg"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        panel = self.card(dialog)
        panel.pack(fill="both", expand=True, padx=18, pady=18)
        self.label(panel, "CHANGE PASSWORD", 14, COLORS["cyan"], True).pack(anchor="w", padx=22, pady=(18, 6))
        self.label(panel, "Use at least 6 characters. Your new password will be securely hashed.", 9, COLORS["muted"]).pack(anchor="w", padx=22, pady=(0, 14))
        entries = {}
        for field_name in ("Current Password", "New Password", "Confirm New Password"):
            self.label(panel, field_name, 10, COLORS["white"], True).pack(anchor="w", padx=22, pady=(7, 3))
            entry = tk.Entry(panel, show="*", font=("Segoe UI", 10), relief="flat", width=34)
            entry.pack(fill="x", padx=22, ipady=7)
            entries[field_name] = entry

        show_passwords = tk.BooleanVar(value=False)
        def toggle_password_visibility():
            visible = not show_passwords.get()
            show_passwords.set(visible)
            mask = "" if visible else "*"
            for password_entry in entries.values():
                password_entry.configure(show=mask)
            visibility_button.configure(
                text="HIDE PASSWORDS" if visible else "SHOW PASSWORDS"
            )

        visibility_button = self.btn(
            panel, "SHOW PASSWORDS", toggle_password_visibility, primary=False, width=18
        )
        visibility_button.pack(anchor="w", padx=22, pady=(8, 2))

        def save_password():
            current = entries["Current Password"].get()
            new = entries["New Password"].get()
            confirm = entries["Confirm New Password"].get()
            if not current or not new or not confirm:
                messagebox.showwarning("Missing Information", "Complete all password fields.", parent=dialog)
                return
            if new != confirm:
                messagebox.showerror("Password Mismatch", "The new password and confirmation do not match.", parent=dialog)
                return
            if len(new.strip()) < 6:
                messagebox.showwarning("Weak Password", "Use a password with at least 6 characters.", parent=dialog)
                return
            ok, message = self.store.change_password(username, current, new)
            if not ok:
                messagebox.showerror("Password Not Changed", message, parent=dialog)
                return
            messagebox.showinfo("Password Changed", message, parent=dialog)
            dialog.destroy()
            refreshed = self.store.user(username)
            if refreshed:
                self.current_user = dict(refreshed)

        controls = tk.Frame(panel, bg=COLORS["card"])
        controls.pack(fill="x", padx=22, pady=18)
        self.btn(controls, "SAVE NEW PASSWORD", save_password, width=20).pack(side="left", padx=(0, 8))
        self.btn(controls, "CANCEL", dialog.destroy, primary=False, width=12).pack(side="left")
        entries["Current Password"].focus_set()

    def customer_reservation_action(self, tree):
        selection = tree.selection()
        if not selection:
            messagebox.showinfo("Select Booking", "Choose a reservation first.")
            return
        self.show_reservation_details(selection[0], customer_view=True)

    def show_booking(self):
        self.clear()
        self.header("Create Booking", "Your booking request will remain Pending until reviewed by the admin.")
        outer = tk.Frame(self.page, bg=COLORS["bg"])
        outer.pack(fill="both", expand=True, padx=35, pady=5)
        left = self.card(outer); left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right = self.card(outer); right.pack(side="right", fill="both", expand=True, padx=(8, 0))
        values = {}
        self.label(left, "VEHICLE", 11, COLORS["cyan"], True).pack(anchor="w", padx=22, pady=(18, 4))
        values["vehicle"] = tk.StringVar(value=self.selected_vehicle)
        vehicle = ttk.Combobox(left, textvariable=values["vehicle"], values=VEHICLES, state="readonly")
        vehicle.pack(fill="x", padx=22)
        self.label(left, "SERVICE", 11, COLORS["cyan"], True).pack(anchor="w", padx=22, pady=(14, 4))
        values["service"] = tk.StringVar(value=f"{SERVICES[0]} — {money(PRICES[SERVICES[0]][values['vehicle'].get()])}")
        service = ttk.Combobox(left, textvariable=values["service"], values=service_options(values["vehicle"].get()), state="readonly")
        service.pack(fill="x", padx=22)
        service_price_label = self.label(
            left, f"Service price: {money(PRICES[service_name(values['service'].get())][values['vehicle'].get()])}",
            9, COLORS["cyan"], True
        )
        service_price_label.pack(anchor="w", padx=22, pady=(4, 0))
        self.label(left, "RESERVATION DATE", 11, COLORS["cyan"], True).pack(anchor="w", padx=22, pady=(14, 4))
        date_row = tk.Frame(left, bg=COLORS["card"]); date_row.pack(fill="x", padx=22)
        values["date"] = tk.StringVar(value=business_now().date().strftime("%m/%d/%Y"))
        date_entry = tk.Entry(date_row, textvariable=values["date"], font=("Segoe UI", 10), relief="flat")
        date_entry.pack(side="left", fill="x", expand=True, ipady=7)
        def choose_date():
            try:
                from tkcalendar import Calendar
            except ImportError:
                messagebox.showinfo("Calendar dependency", "Install the calendar widget with:\n\npython -m pip install tkcalendar")
                return
            popup = tk.Toplevel(self); popup.title("Choose reservation date"); popup.configure(bg=COLORS["card"])
            cal = Calendar(popup, selectmode="day", date_pattern="mm/dd/yyyy", mindate=business_now().date())
            cal.pack(padx=12, pady=12)
            def choose():
                values["date"].set(cal.get_date()); popup.destroy()
            self.btn(popup, "SELECT DATE", choose).pack(pady=(0, 12))
            popup.transient(self); popup.grab_set()
        self.btn(date_row, "CALENDAR", choose_date, primary=False).pack(side="left", padx=(7, 0))
        self.label(left, "TIME", 11, COLORS["cyan"], True).pack(anchor="w", padx=22, pady=(14, 4))
        values["time"] = tk.StringVar(value=TIMES[0])
        time_grid = tk.Frame(left, bg=COLORS["card"])
        time_grid.pack(fill="x", padx=22, pady=(2, 4))
        time_buttons = {}

        def selected_date_text():
            try:
                return datetime.strptime(values["date"].get().strip(), "%m/%d/%Y").strftime("%m/%d/%Y")
            except ValueError:
                return ""

        def time_is_available(time_value):
            date_text = selected_date_text()
            return bool(date_text) and slot_is_future(date_text, time_value)

        def refresh_time_buttons(*_):
            date_text = selected_date_text()
            for name, button in time_buttons.items():
                future = bool(date_text) and time_is_available(name)
                selected = values["time"].get() == name
                button.configure(
                    state="normal" if future else "disabled",
                    bg=(COLORS["cyan"] if selected else COLORS["button2"]) if future else "#3b4652",
                    fg="white" if future else "#9aa4ad",
                    activebackground=COLORS["cyan"] if future else "#3b4652",
                    cursor="hand2" if future else "arrow",
                    highlightthickness=2 if selected and future else 0,
                    highlightbackground=COLORS["cyan"])

        def select_time(time_value):
            if not time_is_available(time_value):
                messagebox.showwarning("Time Unavailable", "This reservation time has already passed. Please select a future time slot.")
                values["time"].set("")
                refresh_time_buttons()
                refresh_bay_buttons()
                return
            values["time"].set(time_value)
            refresh_time_buttons()
            refresh_bay_buttons()

        for index, time_value in enumerate(TIMES):
            button = tk.Button(
                time_grid, text=time_value,
                command=lambda value=time_value: select_time(value),
                font=("Segoe UI", 9, "bold"), fg="white", bg=COLORS["button2"],
                activebackground=COLORS["cyan"], activeforeground="white",
                relief="flat", bd=0, cursor="hand2", pady=7, highlightthickness=0)
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0, 5), pady=3)
            time_buttons[time_value] = button
        time_grid.columnconfigure(0, weight=1)
        time_grid.columnconfigure(1, weight=1)

        price_label = self.label(left, "Total: --", 15, COLORS["cyan"], True)
        price_label.pack(anchor="w", padx=22, pady=16)
        self.label(right, "CARWASH BAY", 11, COLORS["cyan"], True).pack(anchor="w", padx=20, pady=(14, 4))
        values["bay"] = tk.StringVar(value=BAYS[0])
        bay_grid = tk.Frame(right, bg=COLORS["card"])
        bay_grid.pack(fill="x", padx=20, pady=(2, 4))
        bay_buttons = {}

        def refresh_bay_buttons(*_):
            date_text = selected_date_text()
            selected_still_available = False
            for bay_name, button in bay_buttons.items():
                available = bool(date_text) and bool(values["time"].get()) and time_is_available(values["time"].get()) and self.store.bay_available(
                    bay_name, date_text, values["time"].get())
                selected = values["bay"].get() == bay_name
                if selected and available:
                    selected_still_available = True
                button.configure(text=bay_name,
                                 bg=(COLORS["cyan"] if selected else COLORS["button2"]) if available else "#3b4652",
                                 fg="white" if available else "#9aa4ad",
                                 state="normal" if available else "disabled",
                                 activebackground=COLORS["cyan"] if available else "#3b4652",
                                 cursor="hand2" if available else "arrow",
                                 highlightthickness=2 if selected and available else 0,
                                 highlightbackground=COLORS["cyan"])
            if not selected_still_available and values["bay"].get():
                values["bay"].set("")

        def select_bay(bay_name):
            date_text = selected_date_text()
            if not date_text or not values["time"].get() or not time_is_available(values["time"].get()) or not self.store.bay_available(bay_name, date_text, values["time"].get()):
                messagebox.showwarning("Bay Unavailable", "This bay is not available for the selected date and time. Please choose another available slot.")
                refresh_bay_buttons()
                return
            values["bay"].set(bay_name)
            refresh_bay_buttons()

        def rebuild_bay_buttons():
            for child in bay_grid.winfo_children():
                child.destroy()
            bay_buttons.clear()
            for index, bay_name in enumerate(BAYS):
                button = tk.Button(
                    bay_grid, text=bay_name,
                    command=lambda name=bay_name: select_bay(name),
                    font=("Segoe UI", 9, "bold"), fg="white", bg=COLORS["button2"],
                    activebackground=COLORS["cyan"], activeforeground="white",
                    relief="flat", bd=0, cursor="hand2", pady=7, highlightthickness=0)
                button.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0, 5), pady=3)
                bay_buttons[bay_name] = button
            bay_grid.columnconfigure(0, weight=1)
            bay_grid.columnconfigure(1, weight=1)
            refresh_bay_buttons()
            if values["bay"].get() in bay_buttons:
                select_bay(values["bay"].get())

        rebuild_bay_buttons()
        initial_date = selected_date_text()
        first_future = next((slot for slot in TIMES if initial_date and time_is_available(slot)), "")
        values["time"].set(first_future)
        refresh_time_buttons()
        refresh_bay_buttons()

        preview = tk.Label(right, text="", justify="left", anchor="nw", font=("Segoe UI", 11), fg="#d9e6ef", bg=COLORS["card2"], padx=18, pady=18)
        preview.pack(fill="both", expand=True, padx=20, pady=20)
        def refresh_service_dropdown(*_):
            vehicle_name = values["vehicle"].get()
            current_service = service_name(values["service"].get()) if values["service"].get() else SERVICES[0]
            if current_service not in SERVICES:
                current_service = SERVICES[0]
            service.configure(values=service_options(vehicle_name))
            values["service"].set(f"{current_service} — {money(PRICES[current_service][vehicle_name])}")

        def update_preview(*_):
            v, s = values["vehicle"].get(), service_name(values["service"].get())
            total = PRICES[s][v]
            dp = round(total * DOWNPAYMENT_RATE, 2)
            service_price_label.config(text=f"Service price: {money(total)}")
            price_label.config(text=f"Total: {money(total)}")
            preview.config(text=f"INVOICE:\n\nVehicle: {v}\nService: {s}\nDate: {values['date'].get()}\nTime: {values['time'].get()}\n{values['bay'].get()}\n\nTotal: {money(total)}\nRequired 30% downpayment: {money(dp)}\nRemaining balance after downpayment: {money(total-dp)}\n\nBooking status after submission: PENDING")
            refresh_bay_buttons()
        vehicle.bind("<<ComboboxSelected>>", refresh_service_dropdown)
        def on_date_or_time_change(*_):
            date_text = selected_date_text()
            if date_text:
                try:
                    chosen_day = datetime.strptime(date_text, "%m/%d/%Y").date()
                except ValueError:
                    chosen_day = None
                if chosen_day and chosen_day < business_now().date():
                    values["time"].set("")
                elif values["time"].get() and not time_is_available(values["time"].get()):
                    values["time"].set("")
            refresh_time_buttons()
            refresh_bay_buttons()
            update_preview()
        values["date"].trace_add("write", on_date_or_time_change)
        values["time"].trace_add("write", update_preview)
        values["bay"].trace_add("write", update_preview)
        values["vehicle"].trace_add("write", update_preview)
        values["service"].trace_add("write", update_preview)
        update_preview()
        def periodic_availability_check():
            if not self.winfo_exists():
                return
            if not time_is_available(values["time"].get()) if values["time"].get() else False:
                values["time"].set("")
            refresh_time_buttons()
            refresh_bay_buttons()
            self.after(15000, periodic_availability_check)
        self.after(15000, periodic_availability_check)
        def submit():
            try:
                chosen = datetime.strptime(values["date"].get().strip(), "%m/%d/%Y").date()
            except ValueError:
                messagebox.showerror("Invalid Date", "Choose a date using the calendar or MM/DD/YYYY format.")
                return
            now = business_now()
            if chosen < now.date():
                messagebox.showerror("Invalid Date", "Reservation date cannot be in the past.")
                return
            v, s, t, b = values["vehicle"].get(), service_name(values["service"].get()), values["time"].get(), values["bay"].get()
            date_text = chosen.strftime("%m/%d/%Y")
            if not t or not slot_is_future(date_text, t, business_now()):
                messagebox.showerror("Time Expired", "This reservation time has already passed. Please select a future time slot.")
                refresh_time_buttons()
                refresh_bay_buttons()
                return
            if not b:
                messagebox.showerror("Select Bay", "Please select an available carwash bay.")
                return
            if not self.store.bay_available(b, date_text, t):
                messagebox.showerror("Bay Unavailable", f"{b} is unavailable at {t} on {date_text}. Please choose another available bay.")
                refresh_bay_buttons()
                return
            total = PRICES[s][v]
            try:
                rid = self.store.create_reservation({"username": self.current_user["username"],
                    "customer": self.current_user["full_name"], "contact": self.current_user["contact"],
                    "vehicle": v, "service": s, "date": date_text, "time": t, "bay": b, "total": total})
            except ValueError as exc:
                messagebox.showerror("Reservation Not Available", str(exc))
                refresh_time_buttons()
                refresh_bay_buttons()
                return
            messagebox.showinfo("Booking Submitted", f"Your booking request {rid} has been submitted.\nStatus: PENDING")
            self.show_reservation_details(rid, customer_view=True)
        bottom = tk.Frame(self.page, bg=COLORS["bg"]); bottom.pack(fill="x", padx=35, pady=(0, 12))
        self.btn(bottom, "SUBMIT BOOKING REQUEST", submit, width=25).pack(side="right")
        self.btn(bottom, "BACK TO DASHBOARD", self.show_customer_dashboard, primary=False).pack(side="left")

    def detail_rows(self, parent, rows, label_width=29, status_colors=None):
        """Render name/value pairs in an aligned grid so both detail cards line up."""
        grid = tk.Frame(parent, bg=COLORS["card"])
        grid.pack(fill="x", padx=20, pady=(0, 8))
        grid.grid_columnconfigure(1, weight=1)
        value_labels = []
        name_req = 0
        for row_index, (name, value) in enumerate(rows):
            name_label = self.label(grid, name + ":", 10, COLORS["muted"], True, width=label_width,
                                    anchor="w")
            name_label.grid(row=row_index, column=0, sticky="w", padx=(0, 8), pady=2)
            name_req = max(name_req, name_label.winfo_reqwidth())
            color = COLORS["white"]
            if "status" in name.lower():
                color = COLORS["cyan"]
                if status_colors:
                    color = status_colors.get(str(value), COLORS["cyan"])
            value_label = self.label(grid, str(value), 10, color, True, anchor="w", wraplength=190)
            value_label.grid(row=row_index, column=1, sticky="w", pady=2)
            value_labels.append(value_label)
        return value_labels, name_req

    def payment_reference_preview(self, parent, payments, rid, customer_view=False):
        """Show the stored payment receipt at the bottom of the Payment Details card."""
        image_payment = next((p for p in payments if self.store.payment_image_path(p)), None)
        image_path = self.store.payment_image_path(image_payment) if image_payment else None
        wrapper = tk.Frame(parent, bg=COLORS["card"])
        wrapper.pack(fill="x", padx=20, pady=(6, 12))
        self.label(wrapper, "PAYMENT REFERENCE IMAGE", 10, COLORS["cyan"], True).pack(
            anchor="w", pady=(0, 2))
        if image_payment and image_path:
            reference_name = (image_payment.get("reference_image_name")
                              or image_path.name or "Uploaded image")
            self.label(wrapper,
                       f"PAY-{int(image_payment['payment_id']):03d}  •  {reference_name}",
                       9, COLORS["muted"], wraplength=260, justify="left").pack(
                           anchor="w", pady=(0, 6))
            photo = load_payment_image(image_path, max_width=260, max_height=220)
            if photo is not None:
                preview = tk.Label(wrapper, image=photo, bg=COLORS["card2"],
                                   highlightbackground="#23374e", highlightthickness=1)
                preview.image = photo
                preview.pack(anchor="w", pady=(0, 6))
            else:
                self.label(wrapper, f"Image file: {image_path.name} (preview unavailable)",
                           9, COLORS["muted"]).pack(anchor="w", pady=(0, 6))
            controls = tk.Frame(wrapper, bg=COLORS["card"])
            controls.pack(anchor="w")
            self.btn(controls, "VIEW FULL IMAGE",
                     lambda p=image_payment: self.show_payment_image(p), width=15).pack(
                         side="left", padx=(0, 6))
            self.btn(controls, "OPEN IMAGE FILE",
                     lambda path=image_path: self.open_payment_image_file(path),
                     primary=False, width=15).pack(side="left")
            return
        self.label(wrapper, "No payment reference image has been uploaded for this reservation yet.",
                   9, COLORS["muted"], wraplength=260, justify="left").pack(
                       anchor="w", pady=(0, 4))
        reservation = self.store.get_reservation(rid)
        can_upload = (customer_view and reservation
                      and reservation.get("status") not in ("Rejected", "Completed", "Cancelled")
                      and self.store.available_to_pay(rid) > 0)
        if can_upload:
            self.btn(wrapper, "UPLOAD PAYMENT REFERENCE IMAGE",
                     lambda: self.show_payment(rid), width=29).pack(anchor="w", pady=(4, 0))

    def downpayment_error_label(self, parent, eligibility, wraplength=480):
        """Return a red eligibility error label for the disabled 30% option."""
        if not eligibility or eligibility.get("downpayment_available"):
            return None
        message = eligibility.get("downpayment_message") or ""
        if not message:
            return None
        return self.label(parent, message, 9, ERROR_COLOR, True,
                          wraplength=wraplength, justify="left")

    def refund_details_card(self, parent, reservation, refund, customer_view=False):
        """Show refund status, account details, and role-appropriate actions."""
        rid = reservation["reservation_id"]
        status = str(refund.get("status") or "Pending")
        status_colors = {"Pending": COLORS["yellow"], "Processing": COLORS["cyan"],
                         "Completed": COLORS["green"]}
        status_color = status_colors.get(status, COLORS["cyan"])
        method_provided = refund_details_complete(
            refund.get("refund_method"), refund.get("account_holder"),
            refund.get("account_number"), refund.get("bank_name"))
        card = self.card(parent)
        card.pack(fill="x", padx=22, pady=(0, 8))
        title_row = tk.Frame(card, bg=COLORS["card"])
        title_row.pack(fill="x", padx=20, pady=(10, 2))
        self.label(title_row, "REFUND PAYMENT DETAILS", 13, COLORS["cyan"], True).pack(
            side="left")
        self.label(title_row,
                   f"{refund.get('refund_id') or 'REFUND'}  •  Status: {status}",
                   10, status_color, True).pack(side="left", padx=(12, 0))

        if customer_view:
            if status == "Completed":
                notice = ("Your refund has been completed. Keep this record for your reference.")
                notice_color = COLORS["green"]
            elif not method_provided:
                notice = ("Your booking was rejected. Provide your GCash or bank transfer refund "
                          "details so the admin can return your confirmed payment.")
                notice_color = COLORS["yellow"]
            elif status == "Processing":
                notice = ("The admin is currently processing your refund. Keep these account "
                          "details accurate until the refund is completed.")
                notice_color = COLORS["cyan"]
            else:
                notice = ("Your refund details have been received. The admin will send the "
                          "refund to the account shown below.")
                notice_color = COLORS["muted"]
        else:
            if status == "Completed":
                notice = (f"Refund completed on {format_timestamp(refund.get('completed_at'))} "
                          f"by {refund.get('processed_by') or 'an admin'}.")
                notice_color = COLORS["green"]
            elif not method_provided:
                notice = ("Waiting for the customer to submit complete GCash or bank transfer "
                          "refund details. The refund cannot be processed yet.")
                notice_color = COLORS["yellow"]
            elif status == "Processing":
                notice = ("The refund is being processed outside the system. Mark it completed "
                          "only after the money has been sent.")
                notice_color = COLORS["cyan"]
            else:
                notice = ("Refund details have been received. Send the amount manually, then "
                          "mark the refund as processing.")
                notice_color = COLORS["muted"]
        self.label(card, notice, 9, notice_color, True, wraplength=760,
                   justify="left").pack(anchor="w", padx=20, pady=(2, 6))

        methods = refund.get("payment_methods") or []
        method_text = (", ".join(str(item) for item in methods)
                       if isinstance(methods, (list, tuple)) else str(methods))
        original_amount = refund.get("confirmed_paid")
        if original_amount is None:
            original_amount = refund.get("amount") or 0
        rows = [
            ("Refund ID", refund.get("refund_id") or "N/A"),
            ("Original Payment Amount", money(original_amount)),
            ("Original Payment Method", method_text or "N/A"),
            ("Refund Amount", money(refund.get("amount") or 0)),
            ("Refund Method", refund.get("refund_method") or "Not provided yet"),
        ]
        if refund.get("refund_method") == "Bank Transfer":
            rows.append(("Bank Name", refund.get("bank_name") or "Not provided yet"))
        account_display = refund.get("account_number") or "Not provided yet"
        if customer_view and refund.get("account_number"):
            account_display = mask_account_number(account_display)
        rows.extend([
            ("Account Holder Name", refund.get("account_holder") or "Not provided yet"),
            ("Account Number", account_display),
            ("Refund Status", status),
            ("Refund Date", format_refund_date(refund.get("refund_date"))),
            ("Requested On", format_timestamp(refund.get("created_at"))),
            ("Last Updated", format_timestamp(refund.get("updated_at"))),
        ])
        if refund.get("completed_at"):
            rows.append(("Completed On", format_timestamp(refund.get("completed_at"))))
        if refund.get("reference"):
            rows.append(("Refund Reference Number", refund.get("reference")))
        if refund.get("processed_by"):
            rows.append(("Processed By", refund.get("processed_by")))
        self.detail_rows(card, rows, status_colors=status_colors)

        controls = tk.Frame(card, bg=COLORS["card"])
        if customer_view:
            if status != "Completed":
                action_label = ("UPDATE REFUND DETAILS" if method_provided
                                else "PROVIDE REFUND DETAILS")
                self.btn(controls, action_label,
                         lambda: self.show_refund_details_form(rid), width=24).pack(side="left")
                controls.pack(anchor="w", padx=20, pady=(2, 12))
        elif status != "Completed":
            if method_provided:
                self.btn(controls, "RECORD REFUND",
                         lambda: self.admin_update_refund(refund.get("refund_id"), rid),
                         width=18).pack(side="left")
                controls.pack(anchor="w", padx=20, pady=(2, 12))
            else:
                self.label(controls, "Waiting for complete customer refund details.",
                           9, COLORS["muted"]).pack(side="left")
                controls.pack(anchor="w", padx=20, pady=(2, 12))

    def refund_dashboard_section(self, parent, refunds):
        """Customer dashboard summary for tracking refund status."""
        if not refunds:
            return
        status_colors = {"Pending": COLORS["yellow"], "Processing": COLORS["cyan"],
                         "Completed": COLORS["green"]}
        card = self.card(parent)
        card.pack(fill="x", padx=30, pady=(12, 0))
        self.label(card, "REFUND PAYMENT DETAILS", 12, COLORS["cyan"], True).pack(
            anchor="w", padx=20, pady=(12, 2))
        self.label(card, "Track your refund from pending to completed.", 9,
                   COLORS["muted"]).pack(anchor="w", padx=20, pady=(0, 6))
        for refund in refunds:
            rid = refund.get("reservation_id")
            status = str(refund.get("status") or "Pending")
            status_color = status_colors.get(status, COLORS["cyan"])
            method_provided = refund_details_complete(
                refund.get("refund_method"), refund.get("account_holder"),
                refund.get("account_number"), refund.get("bank_name"))
            line = tk.Frame(card, bg=COLORS["card"])
            line.pack(fill="x", padx=18, pady=3)
            self.label(line, f"{refund.get('refund_id')}  •  Reservation {rid}", 9,
                       COLORS["muted"], True).pack(side="left")
            self.label(line, f"{money(refund.get('amount') or 0)}  •  {status}  •  "
                             f"{refund.get('refund_method') or 'Details not provided'}",
                       10, status_color, True).pack(side="left", padx=(14, 0))
            if status == "Completed":
                action_label = "VIEW REFUND"
            elif method_provided:
                action_label = "UPDATE DETAILS"
            else:
                action_label = "PROVIDE DETAILS"
            completed = status == "Completed"
            self.btn(
                line, action_label,
                lambda r=rid, done=completed: (
                    self.show_reservation_details(r, customer_view=True) if done
                    else self.show_refund_details_form(r)),
                primary=not completed, width=16
            ).pack(side="right")

    def notification_dashboard_section(self, parent):
        """Show the signed-in customer's latest private notifications."""
        if not self.current_user:
            return
        username = self.current_user["username"]
        rows = self.store.notifications_for_user(username)
        if not rows:
            return
        unread = sum(1 for row in rows if not row.get("read_at"))
        card = self.card(parent)
        card.pack(fill="x", padx=30, pady=(12, 0))
        heading = tk.Frame(card, bg=COLORS["card"])
        heading.pack(fill="x", padx=20, pady=(12, 5))
        self.label(heading, "NOTIFICATIONS", 12, COLORS["cyan"], True).pack(side="left")
        self.label(heading, f"{unread} unread", 9, COLORS["yellow"], True).pack(
            side="left", padx=(10, 0))
        if unread:
            self.btn(heading, "MARK ALL READ",
                     lambda: (self.store.mark_all_notifications_read(username),
                              self.show_customer_dashboard()),
                     primary=False, width=15).pack(side="right")
        for notification in rows[:4]:
            line = tk.Frame(card, bg=COLORS["card"])
            line.pack(fill="x", padx=20, pady=4)
            title_color = COLORS["yellow"] if not notification.get("read_at") else COLORS["white"]
            self.label(line, notification.get("title") or "Notification", 10,
                       title_color, True).pack(anchor="w")
            self.label(line, notification.get("message") or "", 9, COLORS["muted"],
                       wraplength=720, justify="left").pack(anchor="w")
            self.label(line, format_timestamp(notification.get("created_at")),
                       8, COLORS["muted"]).pack(anchor="w")
            if not notification.get("read_at"):
                self.btn(line, "MARK READ",
                         lambda nid=notification.get("notification_id"): (
                             self.store.mark_notification_read(nid, username),
                             self.show_customer_dashboard()),
                         primary=False, width=12).pack(anchor="e")

    def show_refund_details_form(self, rid):
        """Collect or update a customer's GCash or bank transfer refund details."""
        if not self.current_user:
            messagebox.showerror("Sign In Required", "Please log in first.")
            self.show_landing()
            return
        reservation = self.store.get_reservation(rid)
        if not reservation or reservation.get("username") != self.current_user["username"]:
            messagebox.showerror("Access Denied", "That reservation could not be found.")
            return
        if reservation.get("status") != "Rejected":
            messagebox.showinfo("Refund Not Available",
                                "Refund details can only be provided for rejected bookings.")
            self.show_reservation_details(rid, customer_view=True)
            return
        refund = self.store.refund_for_reservation(rid)
        if not refund:
            refund = self.store.ensure_refund_request(rid)
        if not refund:
            messagebox.showinfo("No Refund Required",
                                "No confirmed payment is available to refund for this booking.")
            self.show_reservation_details(rid, customer_view=True)
            return
        if refund.get("status") == "Completed":
            messagebox.showinfo("Refund Completed",
                                "This refund has already been completed.")
            self.show_reservation_details(rid, customer_view=True)
            return

        self.clear()
        self.header("Refund Payment Details",
                    "Provide the GCash or bank account where your refund should be sent.")
        navigation = tk.Frame(self.page, bg=COLORS["bg"])
        navigation.pack(fill="x", padx=24, pady=(0, 4))
        self.btn(navigation, "BACK TO RESERVATION",
                 lambda: self.show_reservation_details(rid, customer_view=True),
                 primary=False).pack(side="left")

        panel = self.card(self.page)
        panel.pack(fill="both", expand=True, padx=150, pady=12)
        self.label(panel, "REFUND ACCOUNT DETAILS", 13, COLORS["cyan"], True).pack(
            pady=(16, 4))
        status = str(refund.get("status") or "Pending")
        self.label(panel,
                   f"Refund ID: {refund.get('refund_id')}  •  Status: {status}  •  "
                   f"Amount: {money(refund.get('amount') or 0)}",
                   10, COLORS["cyan"], True).pack(pady=3)
        methods = refund.get("payment_methods") or []
        method_text = (", ".join(str(item) for item in methods)
                       if isinstance(methods, (list, tuple)) else str(methods))
        self.label(panel,
                   f"Original confirmed payment: "
                   f"{money(refund.get('confirmed_paid') or refund.get('amount') or 0)}  •  "
                   f"Payment method(s): {method_text or 'N/A'}",
                   10, COLORS["white"], True, wraplength=460, justify="center").pack(pady=3)
        if status == "Processing":
            self.label(panel,
                       "This refund is already being processed. Updating these details will "
                       "change where the refund is sent.",
                       9, COLORS["yellow"], True, wraplength=460,
                       justify="center").pack(pady=(4, 0))

        self.label(panel, "Refund method", 10, COLORS["cyan"], True).pack(pady=(12, 3))
        method_var = tk.StringVar(value=refund.get("refund_method") or "GCash")
        ttk.Combobox(panel, textvariable=method_var, values=REFUND_METHODS,
                     state="readonly", width=25).pack()

        self.label(panel, "Account holder name", 10, COLORS["cyan"], True).pack(pady=(10, 3))
        holder_var = tk.StringVar(value=refund.get("account_holder") or "")
        tk.Entry(panel, textvariable=holder_var, font=("Segoe UI", 11),
                 relief="flat", width=32).pack(ipady=7)

        bank_frame = tk.Frame(panel, bg=COLORS["card"])
        self.label(bank_frame, "Bank name", 10, COLORS["cyan"], True).pack(pady=(10, 3))
        bank_var = tk.StringVar(value=refund.get("bank_name") or "")
        tk.Entry(bank_frame, textvariable=bank_var, font=("Segoe UI", 11),
                 relief="flat", width=32).pack(ipady=7)

        number_label = self.label(panel, "", 10, COLORS["cyan"], True)
        number_label.pack(pady=(10, 3))
        number_var = tk.StringVar(value=refund.get("account_number") or "")
        tk.Entry(panel, textvariable=number_var, font=("Segoe UI", 11),
                 relief="flat", width=32).pack(ipady=7)

        def update_number_label(*_):
            if method_var.get() == "GCash":
                bank_frame.pack_forget()
                number_label.config(text="GCash mobile number (10-13 digits)")
            else:
                bank_frame.pack(before=number_label)
                number_label.config(text="Bank account number (6-20 digits)")

        method_var.trace_add("write", update_number_label)
        update_number_label()
        self.label(panel,
                   "Use the same GCash or bank account where you can receive the refund. "
                   "Double-check the name and number before saving.",
                   9, COLORS["muted"], wraplength=460, justify="center").pack(pady=(6, 0))

        def save_refund_details():
            method = method_var.get()
            holder = holder_var.get()
            number = number_var.get()
            bank_name = bank_var.get() if method == "Bank Transfer" else ""
            problem = refund_account_error(method, holder, number, bank_name)
            if problem:
                messagebox.showerror("Invalid Refund Details", problem)
                return
            ok, message = self.store.update_refund_details(
                rid, self.current_user["username"], method, holder, number, bank_name)
            if not ok:
                messagebox.showerror("Refund Details Not Saved", message)
                return
            messagebox.showinfo("Refund Details Saved", message)
            self.show_reservation_details(rid, customer_view=True)

        self.btn(panel, "SAVE REFUND DETAILS", save_refund_details, width=22).pack(
            pady=(12, 4))
        self.btn(panel, "BACK TO RESERVATION",
                 lambda: self.show_reservation_details(rid, customer_view=True),
                 primary=False, width=22).pack(pady=(0, 16))

    def admin_update_refund(self, refund_id, rid):
        """Open the admin form for recording a manually processed refund."""
        if not self.current_user or self.current_user.get("role") != "admin":
            messagebox.showerror("Access Denied", "Only an admin can update a refund.")
            return
        refund = self.store.get_refund(refund_id)
        if not refund:
            messagebox.showerror("Refund Not Found", "That refund request could not be found.")
            return
        dialog = tk.Toplevel(self)
        dialog.title("Record Refund")
        dialog.configure(bg=COLORS["bg"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        panel = self.card(dialog)
        panel.pack(fill="both", expand=True, padx=18, pady=18)
        self.label(panel, "RECORD REFUND", 14, COLORS["cyan"], True).pack(
            anchor="w", padx=22, pady=(18, 5))
        self.label(panel, f"{refund_id}  •  Reservation {rid}", 9,
                   COLORS["muted"], True).pack(anchor="w", padx=22, pady=(0, 10))
        destination = [
            ("Refund Method", refund.get("refund_method") or "Not provided"),
            ("Bank Name", refund.get("bank_name") or "N/A"),
            ("Account Holder", refund.get("account_holder") or "Not provided"),
            ("Account Number", refund.get("account_number") or "Not provided"),
        ]
        for field_name, value in destination:
            self.label(panel, f"{field_name}: {value}", 9, COLORS["white"],
                       True).pack(anchor="w", padx=22, pady=1)
        self.label(panel, "Record only after the refund has actually been sent.",
                   9, COLORS["yellow"], True).pack(anchor="w", padx=22, pady=(8, 5))

        status_var = tk.StringVar(
            value="Completed" if refund.get("status") == "Processing" else "Processing")
        self.label(panel, "Refund Status", 10, COLORS["white"], True).pack(
            anchor="w", padx=22, pady=(8, 3))
        ttk.Combobox(panel, textvariable=status_var, values=REFUND_STATUSES,
                     state="readonly", width=36).pack(fill="x", padx=22)
        self.label(panel, "Refund Amount (PHP)", 10, COLORS["white"], True).pack(
            anchor="w", padx=22, pady=(10, 3))
        amount = tk.Entry(panel, font=("Segoe UI", 10), relief="flat", width=38)
        amount.insert(0, str(refund.get("amount") or ""))
        amount.pack(fill="x", padx=22, ipady=7)
        self.label(panel, "Refund Date (MM/DD/YYYY)", 10, COLORS["white"], True).pack(
            anchor="w", padx=22, pady=(10, 3))
        date_entry = tk.Entry(panel, font=("Segoe UI", 10), relief="flat", width=38)
        date_entry.insert(0, format_refund_date(
            refund.get("refund_date"), fallback=business_now().strftime("%m/%d/%Y")))
        date_entry.pack(fill="x", padx=22, ipady=7)
        self.label(panel, "Transaction Reference", 10, COLORS["white"], True).pack(
            anchor="w", padx=22, pady=(10, 3))
        reference = tk.Entry(panel, font=("Segoe UI", 10), relief="flat", width=38)
        reference.insert(0, refund.get("reference") or "")
        reference.pack(fill="x", padx=22, ipady=7)

        def save():
            ok, message = self.store.update_refund_status(
                refund_id, status_var.get(), self.current_user["username"],
                amount=amount.get(), refund_date=date_entry.get(),
                reference=reference.get())
            if not ok:
                messagebox.showerror("Refund Not Recorded", message, parent=dialog)
                return
            messagebox.showinfo("Refund Recorded", message, parent=dialog)
            dialog.destroy()
            self.show_reservation_details(rid, customer_view=False)

        controls = tk.Frame(panel, bg=COLORS["card"])
        controls.pack(anchor="w", padx=22, pady=(18, 20))
        self.btn(controls, "SAVE REFUND", save, width=16).pack(side="left", padx=(0, 8))
        self.btn(controls, "CANCEL", dialog.destroy, primary=False, width=10).pack(side="left")

    def show_reservation_details(self, rid, customer_view=True):
        r = self.store.get_reservation(rid)
        if not r:
            messagebox.showerror("Not Found", "Reservation could not be found."); return
        if customer_view and r["username"] != self.current_user["username"]:
            messagebox.showerror("Access Denied", "You can only view your own bookings."); return
        self.clear()
        self.header("Reservation Details", f"Reservation ID: {rid}")

        top_navigation = tk.Frame(self.page, bg=COLORS["bg"])
        top_navigation.pack(fill="x", padx=24, pady=(0, 4))
        if customer_view:
            self.btn(top_navigation, "BACK TO DASHBOARD", self.show_customer_dashboard,
                     primary=False).pack(side="left")
        else:
            self.btn(top_navigation, "BACK TO ADMIN", self.show_admin_dashboard,
                     primary=False).pack(side="left")

        details_row = tk.Frame(self.page, bg=COLORS["bg"])
        details_row.pack(fill="x", padx=22, pady=(0, 4))
        details_row.grid_columnconfigure(0, weight=1, uniform="details")
        details_row.grid_columnconfigure(1, weight=1, uniform="details")
        details_row.grid_rowconfigure(0, weight=1)

        left_card = self.card(details_row)
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        right_card = self.card(details_row)
        right_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        payments = self.store.payments_for_reservation(rid)
        payment = payments[0] if payments else None
        pay_status, confirmed, pending, remaining = self.store.payment_status(rid)
        due = round(float(r["total"]) * DOWNPAYMENT_RATE, 2)
        if payment and payment.get("approval_status") == "Approved":
            approval_note = f"Approved by {payment.get('approved_by')} on {format_timestamp(payment.get('approved_at'))}"
        else:
            approval_note = "Not approved yet"
        self.label(left_card, "RESERVATION DETAILS", 13, COLORS["cyan"], True).pack(
            anchor="w", padx=20, pady=(12, 4))
        details = [
            ("Customer Name", r["customer"]), ("Reservation ID", r["reservation_id"]),
            ("Contact Number", r["contact"]), ("Vehicle Type", r["vehicle"]),
            ("Selected Service", r["service"]), ("Booking Date", r["booking_date"]),
            ("Booking Time", r["booking_time"]), ("Carwash Bay", r["bay"]),
            ("Booking Status", r["status"]),
        ]
        left_values, name_req = self.detail_rows(left_card, details)

        self.label(right_card, "PAYMENT DETAILS", 13, COLORS["cyan"], True).pack(
            anchor="w", padx=20, pady=(12, 4))
        payment_details = [
            ("Total Reservation Amount", money(r["total"])),
            ("Required 30% Downpayment", money(due)),
            ("Amount Paid", money(confirmed)),
            ("Remaining Balance", money(remaining)),
            ("Payment Method", payment["method"] if payment else "N/A"),
            ("Transaction Reference Number", payment["reference"] if payment else "N/A"),
            ("Payment Date", format_timestamp(payment["submitted_at"]) if payment else "N/A"),
            ("Payment Status", pay_status),
            ("Payment Approval", approval_note),
        ]
        if pending > 0:
            payment_details.insert(4, ("Awaiting Verification", money(pending)))
        status_colors = {"Fully Paid": COLORS["green"], "Partially Paid": COLORS["yellow"],
                         "Pending": COLORS["yellow"], "Unpaid": COLORS["muted"]}
        right_values, payment_name_req = self.detail_rows(
            right_card, payment_details, status_colors=status_colors)
        eligibility = self.store.payment_eligibility(rid)
        downpayment_error = self.downpayment_error_label(
            right_card, eligibility, wraplength=300)
        if downpayment_error is not None:
            downpayment_error.pack(anchor="w", padx=20, pady=(2, 4))
        self.payment_reference_preview(right_card, payments, rid, customer_view=customer_view)

        wrap_state = {"limits": None}

        def resize_value_labels(*_):
            """Keep long values readable by wrapping them instead of clipping them."""
            page_width = self.page.winfo_width()
            if page_width <= 1:
                return
            card_share = (page_width - 44 - 12) / 2
            groups = ((left_values, name_req), (right_values, payment_name_req))
            limits = [max(50, int(card_share - 50 - width)) for _, width in groups]
            if limits == wrap_state["limits"]:
                return
            wrap_state["limits"] = list(limits)
            for (labels, _), limit in zip(groups, limits):
                for value_label in labels:
                    try:
                        value_label.configure(wraplength=limit)
                    except tk.TclError:
                        return

        details_row.bind("<Configure>", resize_value_labels)
        self.after_idle(resize_value_labels)

        refund = None
        if r["status"] == "Rejected":
            refund = self.store.refund_for_reservation(rid)
            if not refund and confirmed > 0.005:
                refund = self.store.ensure_refund_request(rid)
        if refund:
            self.refund_details_card(self.page, r, refund, customer_view=customer_view)

        history_card = self.card(self.page)
        history_card.pack(fill="x", padx=22, pady=(0, 8))
        self.label(history_card, "PAYMENT HISTORY", 13, COLORS["cyan"], True).pack(
            anchor="w", padx=20, pady=(8, 2))
        self.payment_history(history_card, rid, admin_view=not customer_view)

        actions = tk.Frame(self.page, bg=COLORS["bg"])
        actions.pack(fill="x", padx=22, pady=(0, 6))
        if customer_view:
            if remaining > 0 and r["status"] not in ("Rejected", "Completed", "Cancelled"):
                pay_label = "PAY REMAINING BALANCE" if confirmed > 0 else "SUBMIT DOWNPAYMENT"
                self.btn(actions, pay_label, lambda: self.show_payment(rid),
                         width=20).pack(side="left", padx=4, pady=4)
            self.btn(actions, "GENERATE RECEIPT", lambda: self.generate_receipt(rid),
                     primary=False, width=17).pack(side="left", padx=4, pady=4)
            self.btn(actions, "+ ADD ANOTHER RESERVATION", self.show_booking,
                     width=25).pack(side="left", padx=4, pady=4)
            if r["status"] not in ("Completed", "Rejected", "Cancelled"):
                cancel_button = self.btn(
                    actions, "CANCEL RESERVATION",
                    lambda: self.confirm_cancel_reservation(rid), primary=False, width=21
                )
                cancel_button.configure(bg=COLORS["red"], activebackground="#c75a66")
                cancel_button.pack(side="left", padx=4, pady=4)
        else:
            self.btn(actions, "GENERATE RECEIPT", lambda: self.generate_receipt(rid), primary=False, width=17).pack(side="left", padx=4, pady=4)

    def payment_history(self, parent, rid, admin_view=False):
        """Show every payment recorded for a reservation with per-payment admin actions."""
        payments = self.store.payments_for_reservation(rid)
        wrapper = tk.Frame(parent, bg=COLORS["card2"], highlightbackground="#23374e", highlightthickness=1)
        wrapper.pack(fill="x", padx=14, pady=(0, 6))
        canvas = tk.Canvas(wrapper, bg=COLORS["card2"], highlightthickness=0, borderwidth=0, height=60)
        hbar = ttk.Scrollbar(wrapper, orient="horizontal", command=canvas.xview)
        canvas.configure(xscrollcommand=hbar.set)
        canvas.pack(fill="x", expand=True)
        hbar.pack(fill="x")
        history = tk.Frame(canvas, bg=COLORS["card2"])
        window = canvas.create_window((0, 0), window=history, anchor="nw")

        def sync_scroll(*_):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window, height=history.winfo_reqheight())
            canvas.configure(height=max(40, history.winfo_reqheight()))

        history.bind("<Configure>", sync_scroll)
        headers = ("Payment ID", "Payment Date", "Method", "Amount Paid", "Reference",
                   "Status", "Verified By")
        column_widths = (10, 21, 8, 12, 14, 11, 13)
        for index, title in enumerate(headers):
            self.label(history, title, 9, COLORS["cyan"], True, width=column_widths[index], anchor="w",
                       bg=COLORS["card2"]).grid(row=0, column=index, sticky="w", padx=6, pady=(8, 4))
        if not payments:
            self.label(history, "No payment has been recorded for this reservation yet.", 9,
                       COLORS["muted"], bg=COLORS["card2"]).grid(row=1, column=0, columnspan=len(headers),
                                                                 sticky="w", padx=6, pady=(0, 8))
            sync_scroll()
            return wrapper
        for index, record in enumerate(payments, start=1):
            verification = record.get("verification_status") or "Unverified"
            approved = record.get("approval_status") == "Approved"
            status = "Approved" if approved else verification
            values = (
                f"PAY-{int(record['payment_id']):03d}",
                format_timestamp(record.get("submitted_at")),
                record.get("method") or "N/A",
                money(record.get("amount_submitted") or 0),
                record.get("reference") or "N/A",
                status,
                record.get("verified_by") or "Not yet verified",
            )
            data_row = index * 2 - 1
            for column, value in enumerate(values):
                color = "white"
                if column == 5:
                    color = {"Approved": COLORS["green"], "Verified": COLORS["green"],
                             "Rejected": COLORS["red"], "Unverified": COLORS["yellow"]}.get(status, "white")
                self.label(history, value, 9, color, True, width=column_widths[column], anchor="w",
                           bg=COLORS["card2"]).grid(row=data_row, column=column, sticky="w", padx=6, pady=2)
            image_path = self.store.payment_image_path(record)
            if admin_view or image_path:
                row_actions = tk.Frame(history, bg=COLORS["card2"])
                row_actions.grid(row=data_row + 1, column=0, columnspan=len(headers),
                                 sticky="e", padx=6, pady=(0, 6))
                if image_path:
                    self.btn(row_actions, "VIEW IMAGE", primary=False, width=11,
                             command=lambda p=record: self.show_payment_image(p)).pack(side="left", padx=2)
            if admin_view:
                if verification != "Verified":
                    self.btn(row_actions, "VERIFY", primary=True, width=9,
                             command=lambda pid=record["payment_id"]: self.admin_verify_payment(pid, "Verified", rid)).pack(side="left", padx=2)
                if verification == "Verified" and not approved:
                    self.btn(row_actions, "APPROVE", primary=True, width=9,
                             command=lambda pid=record["payment_id"]: self.admin_approve_payment(pid, rid)).pack(side="left", padx=2)
                if verification == "Verified":
                    self.btn(row_actions, "UNVERIFY", primary=False, width=9,
                             command=lambda pid=record["payment_id"]: self.admin_verify_payment(pid, "Unverified", rid)).pack(side="left", padx=2)
                if verification != "Rejected":
                    self.btn(row_actions, "REJECT", primary=False, width=9,
                             command=lambda pid=record["payment_id"]: self.admin_verify_payment(pid, "Rejected", rid)).pack(side="left", padx=2)
        sync_scroll()
        return wrapper

    def confirm_cancel_reservation(self, rid):
        """Ask for explicit confirmation before cancelling this reservation."""
        r = self.store.get_reservation(rid)
        if not r:
            messagebox.showerror("Cancellation Failed", "This reservation could not be found.")
            return
        if self.current_user and self.current_user.get("role") == "customer" and r["username"] != self.current_user["username"]:
            messagebox.showerror("Access Denied", "You can only cancel your own reservations.")
            return
        if r["status"] in ("Completed", "Rejected", "Cancelled"):
            messagebox.showwarning(
                "Cannot Cancel Reservation",
                f"This reservation cannot be cancelled because its status is {r['status']}."
            )
            return

        dialog = tk.Toplevel(self)
        dialog.title("Confirm Reservation Cancellation")
        dialog.configure(bg=COLORS["card"])
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.grab_set()
        self.label(dialog, "Are you sure you want to cancel this reservation?", 11,
                   COLORS["white"], True, wraplength=360, justify="center").pack(padx=24, pady=(22, 16))
        choices = tk.Frame(dialog, bg=COLORS["card"])
        choices.pack(padx=16, pady=(0, 20))

        def keep_reservation():
            dialog.destroy()

        def cancel_reservation():
            try:
                latest = self.store.get_reservation(rid)
                if not latest or latest["username"] != r["username"]:
                    messagebox.showerror("Cancellation Failed", "The reservation could not be verified.", parent=dialog)
                    return
                if latest["status"] in ("Completed", "Rejected", "Cancelled"):
                    messagebox.showwarning("Cannot Cancel Reservation", "This reservation's status has changed and it can no longer be cancelled.", parent=dialog)
                    dialog.destroy()
                    self.show_reservation_details(rid, customer_view=(self.current_user.get("role") == "customer"))
                    return
                actor = self.current_user["username"] if self.current_user else "system"
                self.store.set_booking_status(rid, "Cancelled", actor)
            except Exception as exc:
                messagebox.showerror("Cancellation Failed", f"The reservation could not be cancelled.\n\n{exc}", parent=dialog)
                return
            dialog.destroy()
            messagebox.showinfo("Reservation Cancelled", f"Reservation {rid} has been cancelled.")
            self.show_reservation_details(rid, customer_view=(self.current_user.get("role") == "customer"))

        self.btn(choices, "YES, CANCEL RESERVATION", cancel_reservation, width=24).pack(side="left", padx=5)
        self.btn(choices, "NO, KEEP RESERVATION", keep_reservation, primary=False, width=22).pack(side="left", padx=5)
        dialog.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - dialog.winfo_width()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.protocol("WM_DELETE_WINDOW", keep_reservation)

    def show_payment(self, rid):
        r = self.store.get_reservation(rid)
        if not r or r["username"] != self.current_user["username"]:
            messagebox.showerror("Access Denied", "Reservation not found."); return
        eligibility = self.store.payment_eligibility(rid)
        if not eligibility or eligibility["outstanding"] <= 0.005:
            messagebox.showinfo("Nothing Due", "This reservation is already fully paid.")
            self.show_reservation_details(rid, customer_view=True); return
        total = eligibility["total"]
        due = eligibility["downpayment"]
        confirmed = eligibility["confirmed"]
        pending = eligibility["pending"]
        remaining = eligibility["outstanding"]
        available = eligibility["outstanding"]
        pay_status, _, _, _ = self.store.payment_status(rid)
        downpayment_available = eligibility["downpayment_available"]
        full_available = eligibility["full_available"]
        default_option = (PAYMENT_OPTION_DOWNPAYMENT if downpayment_available
                          else PAYMENT_OPTION_FULL)
        downpayment_label = (PAYMENT_OPTION_DOWNPAYMENT if downpayment_available
                             else f"{PAYMENT_OPTION_DOWNPAYMENT} — Unavailable")
        full_label = (PAYMENT_OPTION_FULL if full_available
                      else f"{PAYMENT_OPTION_FULL} — Unavailable")
        self.clear()
        self.header("Payment", "Pay the 30% downpayment or settle the full balance.")
        panel = self.card(self.page); panel.pack(fill="both", expand=True, padx=150, pady=12)
        self.label(panel, f"Reservation: {rid}", 13, COLORS["cyan"], True).pack(pady=(16, 4))
        self.label(panel, f"Total: {money(total)}     Required downpayment (30%): {money(due)}", 10, bold=True).pack(pady=3)
        self.label(panel, f"Amount paid so far (confirmed): {money(confirmed)}     Remaining balance: {money(remaining)}     Payment status: {pay_status}", 10, COLORS["cyan"], True).pack(pady=3)
        self.label(panel, "Payment option", 10, COLORS["cyan"], True).pack(pady=(10, 3))
        option = tk.StringVar(value=default_option)
        option_box = tk.Frame(panel, bg=COLORS["card"])
        option_box.pack(pady=(2, 2))
        option_box_inner = tk.Frame(option_box, bg=COLORS["card"])
        option_box_inner.pack()

        def option_radio(text, value, enabled):
            rb = tk.Radiobutton(
                option_box_inner, text=text, variable=option, value=value,
                command=lambda: apply_option(),
                state="normal" if enabled else "disabled",
                font=("Segoe UI", 10, "bold"),
                fg=COLORS["white"] if enabled else COLORS["muted"],
                bg=COLORS["card"], activebackground=COLORS["card"],
                activeforeground=COLORS["cyan"], selectcolor=COLORS["card2"],
                highlightthickness=0, bd=0,
                cursor="hand2" if enabled else "arrow"
            )
            return rb

        option_radio(downpayment_label, PAYMENT_OPTION_DOWNPAYMENT,
                     downpayment_available).pack(anchor="center", pady=(0, 2))
        downpayment_error = self.downpayment_error_label(option_box, eligibility, wraplength=460)
        if downpayment_error is not None:
            downpayment_error.pack(anchor="center", padx=20, pady=(0, 4))
        option_radio(full_label, PAYMENT_OPTION_FULL,
                     full_available).pack(anchor="center", pady=(0, 2))
        if not full_available:
            self.label(option_box, eligibility["full_message"], 9, COLORS["yellow"], True,
                       wraplength=460, justify="center").pack(anchor="center", padx=20, pady=(0, 4))
        self.label(panel, "Choose your payment method", 10, COLORS["cyan"], True).pack(pady=(10, 3))
        method = tk.StringVar(value="")
        ttk.Combobox(panel, textvariable=method, values=PAYMENT_METHODS, state="readonly", width=25).pack()
        qr_label = tk.Label(
            panel,
            image="",
            text="Select a payment method to display the QR code.",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            justify="center"
        )
        qr_label.pack(pady=10)
        payload_label = self.label(panel, "Payload: (select a payment method)", 9, COLORS["muted"])
        payload_label.pack(pady=3)

        def update_qr(*_):
            selected = method.get()
            payload_label.config(text=f"Payload: WASHAPP|{selected}|{rid}|{due:.2f}" if selected
                                 else "Payload: (select a payment method)")
            photo = load_payment_qr(selected) if selected else None
            if photo is None:
                qr_label.config(image="", text="Select a payment method to display the QR code."
                                if not selected else "Could not load the payment QR image.")
                qr_label.image = None
            else:
                qr_label.config(image=photo, text="")
                qr_label.image = photo
        method.trace_add("write", update_qr)
        update_qr()
        self.label(panel, "Payment reference image", 10, COLORS["cyan"], True).pack(pady=(8, 3))
        selected_image = {"path": None, "photo": None}
        upload_row = tk.Frame(panel, bg=COLORS["card"])
        upload_row.pack(pady=(0, 4))
        upload_button = self.btn(upload_row, "UPLOAD PAYMENT REFERENCE IMAGE", lambda: choose_image(), width=29)
        upload_button.pack(side="left", padx=3)
        change_button = self.btn(upload_row, "CHANGE IMAGE", lambda: choose_image(), primary=False, width=15)
        preview_holder = tk.Frame(panel, bg=COLORS["card2"], highlightbackground="#23374e", highlightthickness=1)
        preview_holder.pack(padx=10, pady=6)
        image_preview = tk.Label(
            preview_holder, text="No payment reference image selected.", bg=COLORS["card2"],
            fg=COLORS["muted"], font=("Segoe UI", 9), width=44, height=8
        )
        image_preview.pack(padx=6, pady=6)
        image_info = self.label(
            panel, f"Accepted formats: PNG, JPG, JPEG  •  Maximum size: {format_file_size(MAX_PAYMENT_IMAGE_BYTES)}",
            9, COLORS["muted"]
        )
        image_info.pack(pady=(0, 2))

        def choose_image():
            chosen = filedialog.askopenfilename(
                title="Select Payment Reference Image",
                filetypes=[("Image files", "*.png *.jpg *.jpeg"), ("PNG images", "*.png"),
                           ("JPEG images", "*.jpg *.jpeg"), ("All files", "*.*")]
            )
            if not chosen:
                return
            ok, message = validate_payment_image(chosen)
            if not ok:
                messagebox.showerror("Invalid Payment Image", message)
                return
            photo = load_payment_image(chosen, max_width=320, max_height=190)
            if photo is None:
                messagebox.showerror("Invalid Payment Image",
                                     "This file could not be displayed as an image. "
                                     "Please choose a valid PNG, JPG, or JPEG file.")
                return
            selected_image["path"] = chosen
            selected_image["photo"] = photo
            image_preview.config(image=photo, text="")
            image_preview.image = photo
            image_info.config(
                text=f"Selected: {Path(chosen).name} ({format_file_size(Path(chosen).stat().st_size)})  "
                     f"•  Click CHANGE IMAGE to replace it."
            )
            upload_button.pack_forget()
            change_button.pack(side="left", padx=3)

        downpayment_remaining = max(0.0, round(float(due) - float(confirmed), 2))
        if downpayment_remaining < 0:
            downpayment_remaining = 0.0
        initial_amount = downpayment_remaining if default_option == PAYMENT_OPTION_DOWNPAYMENT else available
        amount_var = tk.StringVar(value=f"{initial_amount:.2f}")
        self.label(panel, "Amount submitted (PHP)", 10, COLORS["cyan"], True).pack(pady=(8, 3))
        amount_entry = tk.Entry(panel, textvariable=amount_var, font=("Segoe UI", 11), relief="flat", width=20, state="readonly", readonlybackground=COLORS["card2"], fg=COLORS["white"])
        amount_entry.pack(ipady=7)
        projection = self.label(panel, "", 9, COLORS["muted"])
        projection.pack(pady=(6, 0))

        def apply_option(*_):
            if option.get() == PAYMENT_OPTION_DOWNPAYMENT:
                amount_var.set(f"{downpayment_remaining:.2f}")
            else:
                amount_var.set(f"{available:.2f}")

        def refresh_projection(*_):
            try:
                value = float(amount_var.get())
            except ValueError:
                value = 0.0
            projection.config(text=f"Balance after this payment: {money(max(0.0, remaining - value))}   "
                                   f"Status after this payment: {payment_status_label(total, confirmed + value, pending)}")

        amount_var.trace_add("write", refresh_projection)
        refresh_projection()

        submission = {"busy": False}

        def submit_payment():
            if submission["busy"]:
                return
            submission["busy"] = True
            try:
                current = self.store.payment_eligibility(rid)
                if not current or current["outstanding"] <= 0.005:
                    messagebox.showinfo("Nothing Due", "This reservation is already fully paid.")
                    self.show_reservation_details(rid, customer_view=True)
                    return
                selected_option = option.get()
                if (selected_option.startswith(PAYMENT_OPTION_DOWNPAYMENT)
                        and not current["downpayment_available"]):
                    messagebox.showwarning("30% Payment Unavailable",
                                           current["downpayment_message"])
                    return
                if (selected_option.startswith(PAYMENT_OPTION_FULL)
                        and not current["full_available"]):
                    messagebox.showwarning("Full Payment Unavailable",
                                           current["full_message"])
                    return
                if not method.get():
                    messagebox.showwarning("Select Payment Method", "Please select GCash or Bank Transfer before submitting your payment.")
                    return
                try:
                    amount = float(amount_var.get())
                except ValueError:
                    messagebox.showerror("Invalid Amount", "Enter a valid numeric amount.")
                    return
                if selected_option.startswith(PAYMENT_OPTION_DOWNPAYMENT):
                    expected = round(max(0.0, float(current["downpayment"]) - float(current["confirmed"])), 2)
                    if abs(amount - expected) > 0.005:
                        messagebox.showerror("Invalid Amount",
                                             f"The amount for Downpayment (30%) must be {money(expected)}.")
                        return
                    if amount > expected + 0.005 or amount > current["outstanding"] + 0.005:
                        messagebox.showerror("Invalid Amount",
                                             "The submitted amount exceeds the required amount for the selected payment option.")
                        return
                elif selected_option.startswith(PAYMENT_OPTION_FULL):
                    expected = round(float(current["outstanding"]), 2)
                    if abs(amount - expected) > 0.005 or amount > expected + 0.005:
                        messagebox.showerror("Invalid Amount",
                                             f"The amount for Full Payment must be {money(expected)}.")
                        return
                if amount <= 0:
                    messagebox.showerror("Invalid Amount", "Amount must be greater than zero.")
                    return
                if amount > current["outstanding"] + 0.005:
                    messagebox.showerror(
                        "Invalid Amount",
                        f"You can pay up to {money(current['outstanding'])} for this reservation. "
                        f"The remaining balance is {money(current['outstanding'])}."
                    )
                    return
                if (selected_option.startswith(PAYMENT_OPTION_DOWNPAYMENT)
                        and amount > current["downpayment_remaining"] + 0.005):
                    messagebox.showerror(
                        "Invalid Amount",
                        f"The 30% down payment option can only cover the remaining "
                        f"down payment of {money(current['downpayment_remaining'])}."
                    )
                    return
                try:
                    self.store.add_payment(
                        rid, method.get(), current["downpayment"], amount,
                        reference_image=selected_image["path"],
                        payment_option=selected_option
                    )
                except ValueError as exc:
                    messagebox.showerror("Payment Not Recorded", str(exc))
                    return
                messagebox.showinfo("Payment Submitted",
                                    "Your payment was recorded as PENDING.\n"
                                    "It becomes successful only after the admin verifies the transaction.\n"
                                    f"Remaining balance after verification: "
                                    f"{money(max(0.0, current['outstanding'] - amount))}")
                self.show_reservation_details(rid, customer_view=True)
            finally:
                submission["busy"] = False
        buttons = tk.Frame(panel, bg=COLORS["card"]); buttons.pack(pady=16)
        self.btn(buttons, "SUBMIT PAYMENT", submit_payment, width=22).pack(side="left", padx=5)
        self.btn(buttons, "CANCEL", lambda: self.show_reservation_details(rid, True), primary=False).pack(side="left", padx=5)

    def show_admin_dashboard(self):
        if not self.current_user or self.current_user["role"] != "admin":
            messagebox.showerror("Access Denied", "Admin access is required."); self.show_landing(); return
        self.clear()
        self.header("Admin Dashboard", "Manage booking approvals, sales summaries, and payments.")
        counts = self.store.counts()
        approved_value, completed_value, paid = self.store.sales_summary()
        collection = self.store.payment_summary()
        summary = self.card(self.page); summary.pack(fill="x", padx=25, pady=5)
        metrics = [
            ("Total Bookings", counts["total"]), ("Pending", counts["pending"]),
            ("Approved", counts["approved"]), ("Rejected", counts["rejected"]),
            ("Completed", counts["completed"]), ("Approved Booking Value", money(approved_value)),
            ("Completed Sales", money(completed_value)), ("Total Collected", money(collection["total_collected"]))
        ]
        for i, (name, value) in enumerate(metrics):
            cell = tk.Frame(summary, bg=COLORS["card"]); cell.grid(row=i//4, column=i%4, sticky="nsew", padx=10, pady=9)
            self.label(cell, name, 9, COLORS["muted"], True).pack()
            self.label(cell, str(value), 13, COLORS["cyan"], True).pack(pady=2)
        for c in range(4): summary.columnconfigure(c, weight=1)
        collection_card = self.card(self.page); collection_card.pack(fill="x", padx=25, pady=(0, 6))
        self.label(collection_card, "PAYMENT SUMMARY", 12, COLORS["cyan"], True).pack(anchor="w", padx=18, pady=(9, 2))
        collection_grid = tk.Frame(collection_card, bg=COLORS["card"])
        collection_grid.pack(fill="x", padx=8, pady=(0, 6))
        collection_metrics = [
            ("Total Amount Collected", money(collection["total_collected"])),
            ("Verified Payments", collection["verified_count"]),
            ("Awaiting Verification", f"{money(collection['pending_amount'])} ({collection['pending_count']})"),
            ("Outstanding Balance", money(collection["outstanding"])),
            ("GCash Collected", money(collection["by_method"].get("GCash", {}).get("verified", 0))),
            ("Bank Transfer Collected", money(collection["by_method"].get("Bank Transfer", {}).get("verified", 0))),
        ]
        for i, (name, value) in enumerate(collection_metrics):
            cell = tk.Frame(collection_grid, bg=COLORS["card"]); cell.grid(row=i//3, column=i%3, sticky="nsew", padx=10, pady=6)
            self.label(cell, name, 9, COLORS["muted"], True).pack()
            self.label(cell, str(value), 12, COLORS["cyan"], True).pack(pady=2)
        for c in range(3): collection_grid.columnconfigure(c, weight=1)
        controls = tk.Frame(self.page, bg=COLORS["bg"]); controls.pack(fill="x", padx=25, pady=8)
        self.label(controls, "Filter:", 10, COLORS["muted"], True, bg=COLORS["bg"]).pack(side="left", padx=(0, 5))
        self.admin_filter = tk.StringVar(value="All")
        filter_combo = ttk.Combobox(controls, textvariable=self.admin_filter, values=["All","Pending","Approved","Rejected","Completed","Cancelled"], state="readonly", width=13)
        filter_combo.pack(side="left")
        self.admin_search = tk.StringVar()
        tk.Entry(controls, textvariable=self.admin_search, width=25, font=("Segoe UI", 10)).pack(side="left", padx=8, ipady=4)
        self.btn(controls, "SEARCH / REFRESH", self.refresh_admin_table, width=17).pack(side="left", padx=4)
        self.btn(controls, "LOGOUT", self.logout, primary=False, width=12).pack(side="right")
        table_frame = self.card(self.page); table_frame.pack(fill="both", expand=True, padx=25, pady=(0, 8))
        cols = ("id","customer","contact","vehicle","service","date","time","bay","total","paid","balance","status","payment")
        self.admin_tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        names = {"id":"Reservation ID","customer":"Customer","contact":"Contact","vehicle":"Vehicle","service":"Service","date":"Date","time":"Time","bay":"Bay","total":"Total","paid":"Amount Paid","balance":"Remaining Balance","status":"Booking","payment":"Payment Status"}
        widths = {"id":100,"customer":115,"contact":100,"vehicle":85,"service":110,"date":90,"time":75,"bay":60,"total":80,"paid":95,"balance":105,"status":80,"payment":95}
        for c in cols:
            self.admin_tree.heading(c, text=names[c]); self.admin_tree.column(c, width=widths[c], anchor="center")

        self.admin_tree.tag_configure("rejected", foreground="#ff4d4d")
        self.admin_tree.tag_configure("approved", foreground="#36d98a")
        self.admin_tree.tag_configure("pending", foreground="#ffd34d")
        self.admin_tree.tag_configure("completed", background="#ffffff", foreground="#111111")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.admin_tree.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 0))
        admin_v_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.admin_tree.yview)
        admin_h_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.admin_tree.xview)
        admin_v_scroll.grid(row=0, column=1, sticky="ns", pady=(8, 0))
        admin_h_scroll.grid(row=1, column=0, sticky="ew")
        self.admin_tree.configure(yscrollcommand=admin_v_scroll.set, xscrollcommand=admin_h_scroll.set)
        actions = tk.Frame(self.page, bg=COLORS["bg"]); actions.pack(fill="x", padx=25, pady=(0, 13))
        self.btn(actions, "APPROVE SELECTED", lambda: self.admin_set_selected("Approved"), width=18).pack(side="left", padx=4)
        self.btn(actions, "REJECT SELECTED", lambda: self.admin_set_selected("Rejected"), primary=False, width=17).pack(side="left", padx=4)
        self.btn(actions, "MARK COMPLETED", lambda: self.admin_set_selected("Completed"), primary=False, width=17).pack(side="left", padx=4)
        self.btn(actions, "VIEW DETAILS / PAYMENT", self.admin_view_selected, width=23).pack(side="left", padx=4)
        self.refresh_admin_table()
        self._admin_view_active = True
        self.schedule_admin_refresh()

    def schedule_admin_refresh(self):
        """Keep the admin table in sync so new payments appear without a manual refresh."""
        job = getattr(self, "_admin_refresh_job", None)
        if job:
            try:
                self.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
        self._admin_refresh_job = self.after(5000, self.auto_refresh_admin_table)

    def auto_refresh_admin_table(self):
        """Periodically reload the admin table while the dashboard is visible."""
        self._admin_refresh_job = None
        if not getattr(self, "_admin_view_active", False):
            return
        self.refresh_admin_table()
        self.schedule_admin_refresh()

    def refresh_admin_table(self):
        if not hasattr(self, "admin_tree"):
            return
        try:
            if not self.admin_tree.winfo_exists():
                return
        except tk.TclError:
            return
        selection = self.admin_tree.selection()
        for item in self.admin_tree.get_children():
            self.admin_tree.delete(item)
        status = self.admin_filter.get() if hasattr(self, "admin_filter") else "All"
        query = self.admin_search.get().strip().lower() if hasattr(self, "admin_search") else ""
        for r in self.store.all_reservations(status):
            searchable = " ".join(str(r[k] or "") for k in ["reservation_id","customer","contact","username","booking_date","service"]).lower()
            if query and query not in searchable:
                continue
            status_key = str(r["status"]).strip().lower()
            row_tag = status_key if status_key in ("rejected", "approved", "pending", "completed") else ""
            self.admin_tree.insert("", "end", iid=r["reservation_id"], values=(
                r["reservation_id"], r["customer"], r["contact"], r["vehicle"], r["service"],
                r["booking_date"], r["booking_time"], r["bay"], money(r["total"]),
                money(r["verified_paid"]), money(r["remaining_balance"]), r["status"],
                r["payment_status"]
            ), tags=(row_tag,) if row_tag else ())
        if selection and self.admin_tree.exists(selection[0]):
            self.admin_tree.selection_set(selection[0])

    def admin_set_selected(self, new_status):
        selection = self.admin_tree.selection() if hasattr(self, "admin_tree") else ()
        if not selection:
            messagebox.showinfo("Select Booking", "Select a booking first."); return
        rid = selection[0]
        r = self.store.get_reservation(rid)
        if new_status in ("Approved", "Rejected") and r["status"] != "Pending":
            messagebox.showwarning("Status Unchanged", f"Only Pending bookings can be {new_status.lower()}."); return
        if new_status == "Completed" and r["status"] != "Approved":
            messagebox.showwarning("Cannot Complete", "Only an Approved booking can be marked Completed."); return
        if new_status == "Approved" and not self.store.bay_available(r["bay"], r["booking_date"], r["booking_time"], exclude_id=rid):
            messagebox.showerror("Bay Conflict", "Another pending or approved booking occupies this bay and time. Resolve the conflict before approval."); return
        if not messagebox.askyesno("Confirm Action", f"Change {rid} status from {r['status']} to {new_status}?"):
            return
        self.store.set_booking_status(rid, new_status, self.current_user["username"])
        messagebox.showinfo("Booking Updated", f"{rid} is now {new_status}.")
        self.show_admin_dashboard()

    def admin_view_selected(self):
        selection = self.admin_tree.selection() if hasattr(self, "admin_tree") else ()
        if not selection:
            messagebox.showinfo("Select Booking", "Select a booking first."); return
        self.show_reservation_details(selection[0], customer_view=False)

    def admin_verify_payment(self, payment_id, status, rid):
        if not self.current_user or self.current_user.get("role") != "admin":
            messagebox.showerror("Access Denied", "Only an authorized admin can verify a payment.")
            return
        if status == "Verified":
            if not messagebox.askyesno("Verify Payment", "Mark this submitted payment as Verified?"):
                return
        ok, message = self.store.verify_payment(payment_id, status, self.current_user["username"])
        if not ok:
            messagebox.showerror("Payment Not Updated", message)
            return
        messagebox.showinfo("Payment Updated", message)
        self.show_reservation_details(rid, customer_view=False)

    def admin_approve_payment(self, payment_id, rid):
        """Approve a verified payment and move the booking along the approval workflow."""
        if not self.current_user or self.current_user.get("role") != "admin":
            messagebox.showerror("Access Denied", "Only an authorized admin can approve a payment.")
            return
        ok, message = self.store.approve_payment(payment_id, self.current_user["username"])
        if not ok:
            messagebox.showerror("Payment Not Approved", message)
            return
        reservation = self.store.get_reservation(rid)
        note = ""
        if reservation and reservation["status"] == "Pending":
            self.store.set_booking_status(rid, "Approved", self.current_user["username"])
            note = f"\n\nReservation {rid} is now Approved."
        elif reservation:
            note = f"\n\nReservation {rid} stays {reservation['status']}."
        messagebox.showinfo("Payment Approved", message + note)
        self.show_reservation_details(rid, customer_view=False)

    def show_payment_image(self, payment):
        """Open a clear, full-size preview of a submitted payment reference image."""
        path = self.store.payment_image_path(payment)
        if not path:
            messagebox.showwarning(
                "Image Not Available",
                "No payment reference image is stored for this payment record."
            )
            return
        dialog = tk.Toplevel(self)
        dialog.title("Payment Reference Image")
        dialog.configure(bg=COLORS["bg"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        panel = self.card(dialog)
        panel.pack(fill="both", expand=True, padx=14, pady=14)
        self.label(panel, "PAYMENT REFERENCE IMAGE", 13, COLORS["cyan"], True).pack(
            anchor="w", padx=18, pady=(14, 4))
        details = (f"Payment: PAY-{int(payment.get('payment_id', 0)):03d}  •  "
                   f"Reservation: {payment.get('reservation_id', 'N/A')}  •  "
                   f"File: {payment.get('reference_image_name') or path.name}")
        self.label(panel, details, 9, COLORS["muted"]).pack(anchor="w", padx=18, pady=(0, 8))
        max_width = max(320, min(820, self.winfo_screenwidth() - 160))
        max_height = max(240, min(560, self.winfo_screenheight() - 220))
        photo = load_payment_image(path, max_width=max_width, max_height=max_height)
        if photo is not None:
            image_label = tk.Label(panel, image=photo, bg=COLORS["card2"],
                                   highlightbackground="#23374e", highlightthickness=1)
            image_label.image = photo
            image_label.pack(padx=18, pady=(0, 10))
        else:
            self.label(panel, f"The image could not be displayed.\nFile: {path}",
                       10, COLORS["muted"], justify="left").pack(anchor="w", padx=18, pady=(0, 10))
        controls = tk.Frame(panel, bg=COLORS["card"])
        controls.pack(fill="x", padx=18, pady=(0, 14))
        self.btn(controls, "OPEN IMAGE FILE",
                 lambda p=path: self.open_payment_image_file(p), width=17).pack(side="left", padx=(0, 6))
        self.btn(controls, "CLOSE", dialog.destroy, primary=False, width=10).pack(side="left")

    def open_payment_image_file(self, path):
        """Open the stored image with the operating system's default image viewer."""
        path = Path(path)
        if not path.is_file():
            messagebox.showerror("Image Not Found", "The payment reference image file could not be found.")
            return
        try:
            os.startfile(str(path))
        except (AttributeError, OSError) as exc:
            messagebox.showerror(
                "Cannot Open Image",
                f"The image could not be opened.\n\n{exc}\n\nImage location:\n{path}"
            )

    def generate_receipt(self, rid):
        r = self.store.get_reservation(rid)
        if not r:
            messagebox.showerror("Not Found", "Reservation not found."); return
        if self.current_user["role"] == "customer" and r["username"] != self.current_user["username"]:
            messagebox.showerror("Access Denied", "You can only generate receipts for your own bookings."); return
        payments = self.store.payments_for_reservation(rid)
        verified = sum(float(p["amount_submitted"]) for p in payments if p["verification_status"] == "Verified")
        latest = payments[0] if payments else None
        balance = max(0, float(r["total"]) - verified)
        status_label, confirmed, pending, remaining = self.store.payment_status(rid)
        reference_image_text = "N/A"
        if latest and latest.get("reference_image"):
            reference_image_text = latest.get("reference_image_name") or Path(latest["reference_image"]).name
        receipt_no = f"RCPT-{rid}-{business_now().strftime('%Y%m%d%H%M%S')}"
        lines = [
            "WASHAPP - SMART CARWASH RESERVATION SYSTEM",
            "RECEIPT - NOT A TAX INVOICE",
            "=" * 48, f"Receipt No.: {receipt_no}", f"Receipt Date: {business_now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Reservation ID: {rid}", f"Customer: {r['customer']}", f"Contact: {r['contact']}",
            f"Vehicle: {r['vehicle']}", f"Service: {r['service']}", f"Date: {r['booking_date']}",
            f"Time: {r['booking_time']}", f"Bay: {r['bay']}", f"Booking Status: {r['status']}",
            "-" * 48, f"Total Service Price: {money(r['total'])}",
            f"Required 30% Downpayment: {money(round(float(r['total'])*DOWNPAYMENT_RATE,2))}",
            f"Verified Amount Paid: {money(verified)}", f"Remaining Balance: {money(balance)}",
            f"Payment Method: {latest['method'] if latest else 'Not submitted'}",
            f"Payment Reference: {latest['reference'] if latest else 'N/A'}",
            f"Payment Reference Image: {reference_image_text}",
            f"Payment Date: {format_timestamp(latest['submitted_at']) if latest else 'N/A'}",
            f"Payment Status: {status_label}",
            f"Payment Approval: {latest.get('approval_status') if latest and latest.get('approval_status') else 'Not approved yet'}",
            "-" * 48, "PAYMENT HISTORY"
        ]
        if payments:
            for record in payments:
                lines.append(
                    f"{record['payment_id']:03d} | {format_timestamp(record.get('submitted_at'))} | "
                    f"{record.get('method')} | {money(record.get('amount_submitted') or 0)} | "
                    f"Ref: {record.get('reference')} | {record.get('verification_status')}"
                )
        else:
            lines.append("No payment recorded for this reservation.")
        lines.append("=" * 48)
        path = RECEIPT_DIR / f"{receipt_no}.txt"
        path.write_text("\n".join(lines), encoding="utf-8")
        messagebox.showinfo("Receipt Generated", f"Receipt saved to:\n{path}")
        try:
            os.startfile(path)
        except (AttributeError, OSError):
            pass

    def logout(self):
        if messagebox.askyesno("Logout", "Are you sure you want to log out?"):
            self.current_user = None
            self.show_landing()

    def on_close(self):
        try:
            self.store.close()
        finally:
            self.destroy()


if __name__ == "__main__":
    app = WashApp()
    app.mainloop()
