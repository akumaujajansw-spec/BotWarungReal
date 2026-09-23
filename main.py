import os
import html
import time
import threading
import base64
from io import BytesIO
from telebot import types

from dotenv import load_dotenv

load_dotenv()

import requests
import telebot

# ============================================================
# KONFIGURASI
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8953615855"))

# JANGAN hard-code API key di source code.
# Set environment variable:
# KLIKQRIS_API_KEY=...
KLIKQRIS_API_KEY = os.getenv("KLIKQRIS_API_KEY")
KLIKQRIS_MERCHANT_ID = os.getenv("KLIKQRIS_MERCHANT_ID", "179009297448")
KLIKQRIS_BASE_URL = os.getenv("KLIKQRIS_BASE_URL", "https://klikqris.com/api").rstrip("/")

PRICE = 85000

# Batas waktu yang diinginkan bot.
# Catatan: dokumentasi create API KlikQRIS tidak menyediakan parameter
# "expired 15 menit" pada request. Karena itu bot menghentikan polling
# setelah 15 menit. Masa berlaku invoice di sisi KlikQRIS mengikuti
# kebijakan/API KlikQRIS.
PAYMENT_TIMEOUT_SECONDS = 15 * 60
STATUS_CHECK_INTERVAL_SECONDS = 5

ALL_GROUP_IDS = [
    -1003721629607,
    -1003646177202,
    -1003727409464,
    -1003713991635,
    -1003839151133,
    -1003561794613,
    -1003634689467,
    -1003853297361,
    -1004451939488,
    -1004486985873,
    -1003813292350
]

if not TOKEN:
    raise RuntimeError("BOT_TOKEN belum diset.")

if not KLIKQRIS_API_KEY:
    raise RuntimeError("KLIKQRIS_API_KEY belum diset.")


bot = telebot.TeleBot(TOKEN)

# chat_id -> informasi transaksi aktif
active_transactions = {}

# Lock agar satu transaksi tidak diproses dua kali.
transaction_lock = threading.Lock()


# ============================================================
# MENU
# ============================================================

def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🛒 Beli Paket VIP 11 Grup (Rp 85.000)"))
    markup.add(types.KeyboardButton("⭐ Testimoni"), types.KeyboardButton("❓ Bantuan"))
    markup.add(types.KeyboardButton("📞 Hubungi Admin"))
    return markup


# ============================================================
# KLIKQRIS API
# ============================================================

def klikqris_headers():
    return {
        "Content-Type": "application/json",
        "x-api-key": KLIKQRIS_API_KEY,
        "id_merchant": KLIKQRIS_MERCHANT_ID,
    }


def create_qris(order_id):
    """
    Membuat transaksi QRIS dinamis melalui KlikQRIS.
    """
    url = f"{KLIKQRIS_BASE_URL}/qris/create"

    payload = {
        "order_id": order_id,
        "id_merchant": KLIKQRIS_MERCHANT_ID,
        "amount": PRICE,
        "keterangan": f"Paket VIP 11 Grup - Telegram {order_id}",
    }

    response = requests.post(
        url,
        json=payload,
        headers=klikqris_headers(),
        timeout=20,
    )

    # Jangan langsung raise_for_status(), karena KlikQRIS bisa mengirim
    # alasan validasi (HTTP 422) dalam body JSON.
    try:
        result = response.json()
    except ValueError:
        result = {}

    if response.status_code >= 400:
        print(f"[KLIKQRIS] HTTP {response.status_code}")
        print(f"[KLIKQRIS] Response: {response.text}")
        message = (
            result.get("message")
            or result.get("error")
            or result.get("errors")
            or response.text
            or f"HTTP {response.status_code}"
        )
        raise RuntimeError(f"KlikQRIS menolak request ({response.status_code}): {message}")

    if not result.get("status"):
        raise RuntimeError(result.get("message", "KlikQRIS menolak transaksi."))

    data = result.get("data") or {}

    if not data.get("order_id"):
        raise RuntimeError("Response KlikQRIS tidak berisi order_id.")

    return data


def get_qris_status(order_id):
    """
    Mengecek status transaksi.
    Status yang didokumentasikan KlikQRIS:
    PENDING / SUCCESS / EXPIRED
    """
    url = f"{KLIKQRIS_BASE_URL}/qris/status/{order_id}"

    response = requests.get(
        url,
        headers=klikqris_headers(),
        timeout=20,
    )

    response.raise_for_status()
    result = response.json()

    if not result.get("status"):
        raise RuntimeError(result.get("message", "Gagal mengambil status transaksi."))

    return result.get("data") or {}


# ============================================================
# UTILITAS QRIS
# ============================================================

def qris_photo_from_data(data):
    """
    Menghasilkan object yang bisa diberikan ke bot.send_photo().
    Prioritas:
    1. qris_image berupa data:image/png;base64,...
    2. download qris_url
    """
    qris_image = data.get("qris_image")

    if isinstance(qris_image, str) and qris_image.startswith("data:image"):
        try:
            encoded = qris_image.split(",", 1)[1]
            return BytesIO(base64.b64decode(encoded))
        except Exception:
            pass

    qris_url = data.get("qris_url")

    if qris_url:
        response = requests.get(qris_url, timeout=20)
        response.raise_for_status()

        photo = BytesIO(response.content)
        photo.name = "qris.png"
        return photo

    return None


# ============================================================
# PENGIRIMAN LINK VIP
# ============================================================

def send_vip_links(user_id, order_id):
    """
    Membuat 11 invite link Telegram sekali pakai.
    member_limit=1 membuat link hanya menerima satu member.
    """
    generated_links = []

    for group_id in ALL_GROUP_IDS:
        invite = bot.create_chat_invite_link(
            chat_id=group_id,
            member_limit=1
        )
        generated_links.append(invite.invite_link)

    links_text = "\n".join(
        f"{index}. {link}"
        for index, link in enumerate(generated_links, start=1)
    )

    bot.send_message(
        user_id,
        (
            "✅ <b>Pembayaran Berhasil!</b>\n\n"
            f"Order ID: <code>{html.escape(order_id)}</code>\n\n"
            "Berikut 11 link akses VIP sekali pakai:\n\n"
            f"{links_text}\n\n"
            "<b>Penting:</b>\n"
            "• Setiap link hanya dapat digunakan 1 kali.\n"
            "• Jika link kadaluarsa artinya sudah berhasil masuk ke grup.\n"
            "• Jika muncul pesan 'To Many Attempts' atau 'Terlalu Banyak Mencoba' tunggu beberapa menit lalu coba klik kembali!!!"
        ),
        parse_mode="HTML"
    )


# ============================================================
# MONITOR PEMBAYARAN
# ============================================================

def finish_transaction(chat_id, order_id):
    with transaction_lock:
        active_transactions.pop(chat_id, None)


def monitor_payment(chat_id, order_id, qr_message_id):
    """
    Memantau status transaksi otomatis maksimal 15 menit.
    """
    started_at = time.time()

    while time.time() - started_at < PAYMENT_TIMEOUT_SECONDS:
        try:
            data = get_qris_status(order_id)
            status = str(data.get("status", "")).upper()

            if status in ("SUCCESS", "PAID"):
                # Idempotency: jangan kirim produk dua kali.
                with transaction_lock:
                    tx = active_transactions.get(chat_id)

                    if not tx or tx.get("order_id") != order_id:
                        return

                    if tx.get("fulfilled"):
                        return

                    tx["fulfilled"] = True

                try:
                    bot.send_chat_action(chat_id, "typing")
                    status_message = bot.send_message(
                        chat_id,
                        "✅ <b>Pembayaran diterima!</b>\n\n"
                        "⏳ Sedang membuat dan mengirimkan 11 link VIP...",
                        parse_mode="HTML",
                    )

                    send_vip_links(chat_id, order_id)

                    try:
                        bot.delete_message(chat_id, status_message.message_id)
                    except Exception:
                        pass

                    try:
                        bot.delete_message(chat_id, qr_message_id)
                    except Exception:
                        pass

                    bot.send_message(
                        chat_id,
                        "🎉 Akses sudah dikirim otomatis. Terima kasih atas pembayarannya!"
                    )

                except Exception as e:
                    print(f"[ERROR] Gagal membuat/mengirim link VIP: {e}")
                    bot.send_message(
                        chat_id,
                        "⚠️ Pembayaran terdeteksi berhasil, tetapi pengiriman link mengalami kendala. "
                        "Silakan hubungi admin."
                    )

                finally:
                    finish_transaction(chat_id, order_id)

                return

            if status == "EXPIRED":
                try:
                    bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=qr_message_id,
                        caption=(
                            "⏰ <b>QRIS Kedaluwarsa</b>\n\n"
                            f"Order ID: <code>{html.escape(order_id)}</code>\n"
                            "Silakan tekan tombol pembelian kembali jika ingin membuat transaksi baru."
                        ),
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

                finish_transaction(chat_id, order_id)
                return

        except Exception as e:
            # Error jaringan sementara tidak langsung menggagalkan transaksi.
            print(f"[WARN] Cek status {order_id}: {e}")

        time.sleep(STATUS_CHECK_INTERVAL_SECONDS)

    # Timeout lokal 15 menit.
    with transaction_lock:
        tx = active_transactions.get(chat_id)
        if tx and tx.get("order_id") == order_id:
            active_transactions.pop(chat_id, None)

    try:
        bot.edit_message_caption(
            chat_id=chat_id,
            message_id=qr_message_id,
            caption=(
                "⏰ <b>Waktu pembayaran berakhir</b>\n\n"
                f"Order ID: <code>{html.escape(order_id)}</code>\n"
                "QR ini tidak lagi dipantau oleh bot.\n"
                "Silakan membuat transaksi baru jika belum melakukan pembayaran."
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass


# ============================================================
# TELEGRAM HANDLERS
# ============================================================

@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.send_chat_action(message.chat.id, "typing")
    time.sleep(1.2)

    bot.reply_to(
        message,
        "Halo! Selamat datang di bot WarungDosa.\n\n"
        "🔥 <b>Paket Hemat:</b> Dapatkan akses ke <b>11 Grup VIP Sekaligus</b> "
        "hanya dengan <b>Rp 85.000</b>!\n\n"
        "Silakan gunakan tombol menu di bawah untuk mulai:",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


@bot.message_handler(
    func=lambda message: message.text == "🛒 Beli Paket VIP 11 Grup (Rp 85.000)"
)
def handle_buy_menu(message):
    chat_id = message.chat.id

    # Cegah user membuat banyak invoice aktif sekaligus.
    with transaction_lock:
        existing = active_transactions.get(chat_id)

    if existing:
        bot.send_message(
            chat_id,
            (
                "⚠️ Anda masih memiliki transaksi aktif.\n\n"
                f"Order ID: <code>{html.escape(existing['order_id'])}</code>\n"
                "Silakan selesaikan pembayaran tersebut terlebih dahulu."
            ),
            parse_mode="HTML"
        )
        return

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "💳 Tampilkan QRIS Pembayaran",
            callback_data="show_qris"
        )
    )

    bot.send_message(
        chat_id,
        "Anda memilih <b>Paket VIP 11 Grup Sekaligus (Rp 85.000)</b>.\n\n"
        "Klik tombol di bawah untuk membuat QRIS dinamis:",
        parse_mode="HTML",
        reply_markup=markup
    )


@bot.message_handler(func=lambda message: message.text == "⭐ Testimoni")
def handle_testimoni(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "🔗 Buka Channel Testimoni",
            url="https://t.me/testiwarungdosaa"
        )
    )

    bot.send_message(
        message.chat.id,
        "⭐ <b>Testimoni Pelanggan WarungDosa</b>\n\n"
        "Silakan klik tombol di bawah:",
        parse_mode="HTML",
        reply_markup=markup
    )


@bot.message_handler(func=lambda message: message.text == "❓ Bantuan")
def handle_faq(message):
    bot.reply_to(
        message,
        "💡 <b>Panduan:</b>\n\n"
        "1. Klik <b>🛒 Beli Paket VIP 11 Grup</b>.\n"
        "2. Klik <b>💳 Tampilkan QRIS Pembayaran</b>.\n"
        "3. Scan QRIS dan bayar sesuai nominal yang tampil.\n"
        "4. Bot akan mengecek pembayaran otomatis.\n"
        "5. Setelah pembayaran berhasil, 11 link sekali pakai dikirim otomatis.\n\n"
        "Tidak perlu kirim screenshot pembayaran.",
        parse_mode="HTML"
    )


@bot.message_handler(func=lambda message: message.text == "📞 Hubungi Admin")
def handle_contact_admin(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "💬 Chat Admin Sekarang",
            url="https://t.me/WarungDosa"
        )
    )

    bot.send_message(
        message.chat.id,
        "💬 Silakan hubungi Admin jika mengalami kendala:",
        reply_markup=markup
    )


# ============================================================
# BUAT QRIS DINAMIS
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data == "show_qris")
def process_show_qris(call):
    chat_id = call.message.chat.id

    bot.answer_callback_query(call.id, "Membuat QRIS dinamis...")
    bot.send_chat_action(chat_id, "upload_photo")

    # Cegah invoice ganda.
    with transaction_lock:
        existing = active_transactions.get(chat_id)

    if existing:
        bot.send_message(
            chat_id,
            (
                "⚠️ Anda sudah memiliki QRIS aktif.\n"
                f"Order ID: <code>{html.escape(existing['order_id'])}</code>"
            ),
            parse_mode="HTML"
        )
        return

    # Order ID unik dan mudah dilacak.
    order_id = f"VIP11-{chat_id}-{int(time.time())}"

    try:
        progress_message = bot.send_message(
            chat_id,
            "⏳ <b>Sedang menyiapkan dan mengirimkan gambar QRIS...</b>",
            parse_mode="HTML",
        )
        data = create_qris(order_id)

        returned_order_id = str(data.get("order_id", order_id))
        total_amount = data.get("total_amount", PRICE)
        expired_at = data.get("expired_at", "-")

        photo = qris_photo_from_data(data)

        caption = (
            "💳 <b>QRIS PEMBAYARAN DINAMIS</b>\n\n"
            "Paket: <b>VIP 11 Grup</b>\n"
            f"Nominal: <b>Rp {int(float(total_amount)):,}</b>\n"
            f"Order ID: <code>{html.escape(returned_order_id)}</code>\n"
            f"Batas pemantauan bot: <b>15 menit</b>\n"
            f"Expired dari KlikQRIS: <b>{html.escape(str(expired_at))}</b>\n\n"
            "Silakan scan QR di atas dan lakukan pembayaran.\n\n"
            "✅ Setelah pembayaran berhasil, bot akan mendeteksi otomatis "
            "dan mengirim 11 link VIP sekali pakai.\n"
            "❌ Tidak perlu mengirim screenshot bukti pembayaran."
        ).replace(",", ".")

        if photo:
            sent = bot.send_photo(
                chat_id,
                photo,
                caption=caption,
                parse_mode="HTML"
            )
            try:
                bot.delete_message(chat_id, progress_message.message_id)
            except Exception:
                pass
        else:
            # Fallback jika API tidak memberikan image.
            direct_url = data.get("direct_url")
            qris_url = data.get("qris_url")

            markup = types.InlineKeyboardMarkup()
            if direct_url:
                markup.add(
                    types.InlineKeyboardButton(
                        "💳 Buka Halaman Pembayaran",
                        url=direct_url
                    )
                )

            bot.send_message(
                chat_id,
                caption + (
                    f"\n\nQRIS URL: {html.escape(str(qris_url))}"
                    if qris_url else ""
                ),
                parse_mode="HTML",
                reply_markup=markup if direct_url else None
            )

            # Karena tidak ada pesan foto, buat pesan teks sebagai tracker.
            sent = bot.send_message(
                chat_id,
                "⏳ <b>Menunggu pembayaran...</b>",
                parse_mode="HTML"
            )
            try:
                bot.delete_message(chat_id, progress_message.message_id)
            except Exception:
                pass

        with transaction_lock:
            active_transactions[chat_id] = {
                "order_id": returned_order_id,
                "created_at": time.time(),
                "fulfilled": False,
            }

        worker = threading.Thread(
            target=monitor_payment,
            args=(chat_id, returned_order_id, sent.message_id),
            daemon=True
        )
        worker.start()

    except requests.RequestException as e:
        print(f"[ERROR] KlikQRIS HTTP error: {e}")
        bot.send_message(
            chat_id,
            "❌ Gagal menghubungi server pembayaran. Silakan coba lagi beberapa saat."
        )

    except Exception as e:
        print(f"[ERROR] Gagal membuat QRIS: {e}")
        bot.send_message(
            chat_id,
            "❌ Gagal membuat QRIS dinamis. Silakan coba lagi atau hubungi admin."
        )


# ============================================================
# JALANKAN BOT
# ============================================================

if __name__ == "__main__":
    print("Bot berjalan...")
    bot.infinity_polling(skip_pending=True)
