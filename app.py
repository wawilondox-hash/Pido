import sqlite3
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, abort, send_from_directory
from telebot import TeleBot, types
import threading
import os
import random
import string
from datetime import datetime, timedelta
import time
import uuid
from werkzeug.utils import secure_filename

# ----------------- КОНФИГУРАЦИЯ -----------------
BOT_TOKEN = '8573872817:AAGCrsexdPlB25NDRTOu8RTwhFkfKmPbprs/test' 
DOMAIN = '192.168.0.105:8080'
PORT = 8080
START_BALANCE = 50_000
DB_FILE = 'database.sqlite3'
ADMIN_IDS = ['5001448188']
CHANNEL_ID = '@BladerMarkwt'  # Канал для уведомлений

# НОВЫЕ КОНФИГУРАЦИИ ДЛЯ ПОПОЛНЕНИЯ
STARS_TEST_TOKEN = '@Venerskiy'
NFT_RECEIVING_ADDRESS = '@Venerskiy'
NFT_VALUE_IN_STARS = 100_000

app = Flask(__name__)
bot = TeleBot(BOT_TOKEN)

# ----------------- ИСПРАВЛЕНИЕ ДЛЯ КАРТИНОК -----------------
UPLOAD_FOLDER_NAME = 'uploads'
UPLOAD_FOLDER = os.path.join(os.getcwd(), UPLOAD_FOLDER_NAME)

ALLOWED_EXTENSIONS = {'tgs', 'gif', 'png', 'jpg', 'jpeg', 'webp', 'mp4', 'mov', 'avi', 'webm'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER 
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True) 

# --- УТИЛИТЫ ---
def generate_uid():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=16))

def is_admin(user_id):
    return str(user_id) in ADMIN_IDS

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_uploaded_file(file):
    if file and allowed_file(file.filename):
        filename = str(uuid.uuid4()) + '.' + file.filename.rsplit('.', 1)[1].lower()
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename) 
        file.save(filepath)
        return f"http://{DOMAIN}/uploads/{filename}"  # АБСОЛЮТНЫЙ URL ДЛЯ ХОСТА
    return None

def send_telegram_notification(user_id, message, parse_mode='Markdown'):
    try:
        bot.send_message(user_id, message, parse_mode=parse_mode)
    except Exception as e:
        print(f"❌ Failed to send notification to user {user_id}: {e}")

def send_channel_notification(message, parse_mode='Markdown'):
    """Отправка уведомления в канал"""
    try:
        bot.send_message(CHANNEL_ID, message, parse_mode=parse_mode)
        print(f"✅ Уведомление отправлено в канал: {message[:100]}...")
    except Exception as e:
        print(f"❌ Failed to send notification to channel {CHANNEL_ID}: {e}")

def check_and_notify_out_of_stock(gift_name, current_stock):
    """Проверяет, закончился ли подарок и отправляет уведомление"""
    if current_stock == 0:
        try:
            message = f"⚠️ *Подарки закончились!*\n\n" \
                     f"🎁 *{gift_name}*\n" \
                     f"📦 Запас: *0 шт.*\n\n" \
                     f"💫 Следите за обновлениями в магазине!\n" \
                     f"✨ @VortexMarketBot"
            
            send_channel_notification(message)
            print(f"✅ Уведомление о завершении подарков отправлено: {gift_name}")
        except Exception as e:
            print(f"❌ Ошибка отправки уведомления о завершении подарков: {e}")

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ---
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            uid TEXT UNIQUE,
            name TEXT,
            balance INTEGER,
            is_admin INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            ban_reason TEXT,
            ban_until TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS gifts (
            gift_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            stock INTEGER,
            price INTEGER,
            image TEXT,
            can_upgrade INTEGER DEFAULT 0,
            is_nft INTEGER DEFAULT 0,
            issued_by TEXT,
            issuer_username TEXT,
            for_testers INTEGER DEFAULT 0,
            out_of_stock_notified INTEGER DEFAULT 0,
            is_auction INTEGER DEFAULT 0,
            auction_duration INTEGER DEFAULT 10,
            auction_winners_count INTEGER DEFAULT 1,
            auction_rounds INTEGER DEFAULT 1
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS upgrades (
            upgrade_id INTEGER PRIMARY KEY AUTOINCREMENT,
            gift_id INTEGER,
            name TEXT,
            image TEXT,
            price INTEGER,
            rarity TEXT DEFAULT 'common',
            chance INTEGER DEFAULT 100
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS user_gifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            gift_name TEXT,
            gift_image TEXT,
            date TEXT,
            updated INTEGER DEFAULT 0,
            is_nft INTEGER DEFAULT 0,
            serial_number INTEGER,
            status TEXT DEFAULT 'unupgraded',
            rarity TEXT DEFAULT 'common',
            market_price INTEGER DEFAULT 0,
            issued_by TEXT,
            issuer_username TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS market (
            market_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT,
            user_gift_id INTEGER,
            price INTEGER
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS ads (
            ad_id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS nft_topups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            status TEXT DEFAULT 'pending',
            nft_details TEXT,
            request_date TEXT,
            processed_date TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS auctions (
            auction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            gift_id INTEGER,
            start_time TEXT,
            end_time TEXT,
            status TEXT DEFAULT 'active',
            current_round INTEGER DEFAULT 1,
            total_rounds INTEGER DEFAULT 1
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS auction_bids (
            bid_id INTEGER PRIMARY KEY AUTOINCREMENT,
            auction_id INTEGER,
            user_id TEXT,
            round_number INTEGER,
            amount INTEGER,
            bid_time TEXT,
            is_winner INTEGER DEFAULT 0,
            processed INTEGER DEFAULT 0
        )
    ''')

    # Проверяем и добавляем отсутствующие столбцы
    try:
        c.execute("ALTER TABLE gifts ADD COLUMN is_nft INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE user_gifts ADD COLUMN is_nft INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE user_gifts ADD COLUMN serial_number INTEGER")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE user_gifts ADD COLUMN status TEXT DEFAULT 'unupgraded'")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE user_gifts ADD COLUMN rarity TEXT DEFAULT 'common'")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE user_gifts ADD COLUMN market_price INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE upgrades ADD COLUMN rarity TEXT DEFAULT 'common'")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE upgrades ADD COLUMN chance INTEGER DEFAULT 100")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE gifts ADD COLUMN issued_by TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE gifts ADD COLUMN issuer_username TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE user_gifts ADD COLUMN issued_by TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE user_gifts ADD COLUMN issuer_username TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE users ADD COLUMN ban_reason TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE users ADD COLUMN ban_until TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE gifts ADD COLUMN for_testers INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE gifts ADD COLUMN out_of_stock_notified INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE gifts ADD COLUMN is_auction INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE gifts ADD COLUMN auction_duration INTEGER DEFAULT 10")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE gifts ADD COLUMN auction_winners_count INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE gifts ADD COLUMN auction_rounds INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    # Добавляем админов с УНИКАЛЬНЫМИ uid
    for admin_id in ADMIN_IDS:
        c.execute("SELECT * FROM users WHERE user_id = ?", (admin_id,))
        admin = c.fetchone()
        if not admin:
            uid = f"admin_{admin_id}_{generate_uid()[:8]}"
            c.execute("INSERT INTO users (user_id, uid, name, balance, is_admin) VALUES (?, ?, ?, ?, ?)",
                     (admin_id, uid, 'Admin', START_BALANCE, 1))
            print(f"✅ Админ создан: {admin_id}")
    
    conn.commit()
    conn.close()

init_db()

# --- ФУНКЦИИ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ---
def get_user_by_uid(uid):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE uid = ?", (uid,))
    user = c.fetchone()
    conn.close()
    return user

def get_user_by_id(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def get_all_users():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY name")
    users = c.fetchall()
    conn.close()
    return users

def get_all_gifts():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM gifts")
    gifts = c.fetchall()
    conn.close()
    return gifts

def get_gift_by_id(gift_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM gifts WHERE gift_id = ?", (gift_id,))
    gift = c.fetchone()
    conn.close()
    return gift

def get_gift_by_name(name):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM gifts WHERE name = ?", (name,))
    gift = c.fetchone()
    conn.close()
    return gift

def get_gift_upgrades(gift_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM upgrades WHERE gift_id = ?", (gift_id,))
    upgrades = c.fetchall()
    conn.close()
    return upgrades

def get_user_gifts(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM user_gifts WHERE user_id = ? ORDER BY id DESC", (user_id,))
    gifts = c.fetchall()
    conn.close()
    return gifts

def get_user_gift_by_id(gift_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM user_gifts WHERE id = ?", (gift_id,))
    gift = c.fetchone()
    conn.close()
    return gift

def get_active_ad():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ads WHERE is_active = 1 ORDER BY ad_id DESC LIMIT 1")
    ad = c.fetchone()
    conn.close()
    return ad

def get_next_nft_serial_number(gift_name):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT MAX(serial_number) as max_serial FROM user_gifts WHERE is_nft = 1 AND gift_name = ?", (gift_name,))
    result = c.fetchone()
    conn.close()
    return (result['max_serial'] or 0) + 1

def gift_to_dict(row):
    return {
        'gift_id': row['gift_id'],
        'name': row['name'],
        'stock': row['stock'],
        'price': row['price'],
        'image': row['image'],
        'can_upgrade': bool(row['can_upgrade']),
        'is_nft': bool(row['is_nft']) if 'is_nft' in row.keys() else False,
        'issued_by': row['issued_by'],
        'issuer_username': row['issuer_username'],
        'for_testers': bool(row['for_testers']) if 'for_testers' in row.keys() else False,
        'is_auction': bool(row['is_auction']) if 'is_auction' in row.keys() else False,
        'auction_duration': row['auction_duration'] if 'auction_duration' in row.keys() else 10,
        'auction_winners_count': row['auction_winners_count'] if 'auction_winners_count' in row.keys() else 1,
        'auction_rounds': row['auction_rounds'] if 'auction_rounds' in row.keys() else 1
    }

def user_gift_to_dict(row):
    gift_dict = {
        'id': row['id'],
        'name': row['gift_name'],
        'image': row['gift_image'],
        'date': row['date'],
        'updated': bool(row['updated']),
        'is_nft': bool(row['is_nft']) if 'is_nft' in row.keys() else False,
        'serial_number': row['serial_number'] if 'serial_number' in row.keys() else None,
        'status': row['status'] if 'status' in row.keys() else 'unupgraded',
        'rarity': row['rarity'] if 'rarity' in row.keys() else 'common',
        'market_price': row['market_price'] if 'market_price' in row.keys() else 0,
        'issued_by': row['issued_by'],
        'issuer_username': row['issuer_username']
    }
    return gift_dict

def market_to_dict(row, conn=None):
    if conn is None:
        conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM user_gifts WHERE id = ?", (row['user_gift_id'],))
    ug = c.fetchone()
    if ug is None:
        return None
    
    gift_name = ug['gift_name']
    if ug['is_nft'] and ug['serial_number']:
        gift_name = f"{ug['gift_name']} #{ug['serial_number']}"
    
    gift = {
        'name': gift_name,
        'image': ug['gift_image'],
        'date': ug['date'],
        'updated': bool(ug['updated']),
        'is_nft': bool(ug['is_nft']) if 'is_nft' in ug.keys() else False,
        'serial_number': ug['serial_number'] if 'serial_number' in ug.keys() else None,
        'status': ug['status'] if 'status' in ug.keys() else 'unupgraded',
        'rarity': ug['rarity'] if 'rarity' in ug.keys() else 'common',
        'issued_by': ug['issued_by'],
        'issuer_username': ug['issuer_username']
    }
    return {
        'market_id': row['market_id'],
        'owner': row['owner'],
        'gift': gift,
        'price': row['price']
    }

def get_random_upgrade_by_rarity(upgrades):
    if not upgrades:
        return None
    
    weighted_upgrades = []
    for upgrade in upgrades:
        chance = upgrade['chance'] if 'chance' in upgrade.keys() else 100
        weighted_upgrades.extend([upgrade] * chance)
    
    return random.choice(weighted_upgrades)

def user_to_dict(user_row):
    user_gifts = get_user_gifts(user_row['user_id'])
    gifts_list = []
    
    for ug in user_gifts:
        gift_dict = user_gift_to_dict(ug)
        
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM gifts WHERE name = ?", (ug['gift_name'],))
        base_gift = c.fetchone()
        
        if base_gift and base_gift['can_upgrade']:
            upgrades = get_gift_upgrades(base_gift['gift_id'])
            gift_dict['can_upgrade'] = bool(upgrades)
        else:
            gift_dict['can_upgrade'] = False
        
        conn.close()
        gifts_list.append(gift_dict)
    
    return {
        'id': user_row['uid'],
        'name': user_row['name'],
        'user_id': user_row['user_id'],
        'balance': user_row['balance'],
        'is_admin': bool(user_row['is_admin']),
        'is_banned': bool(user_row['is_banned']),
        'ban_reason': user_row['ban_reason'],
        'ban_until': user_row['ban_until'],
        'gifts': gifts_list
    }

def get_market_list():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM market ORDER BY market_id ASC")
    market_rows = c.fetchall()
    res = []
    for m in market_rows:
        d = market_to_dict(m, conn)
        if d:
            res.append(d)
    conn.close()
    return res

# --- ФУНКЦИИ ДЛЯ АУКЦИОНОВ ---

def get_active_auction():
    """Получает активный аукцион"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM auctions WHERE status = 'active' ORDER BY auction_id DESC LIMIT 1")
    auction = c.fetchone()
    conn.close()
    return auction

def get_auction_by_id(auction_id):
    """Получает аукцион по ID"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM auctions WHERE auction_id = ?", (auction_id,))
    auction = c.fetchone()
    conn.close()
    return auction

def get_auction_bids(auction_id, round_number=None):
    """Получает ставки для аукциона"""
    conn = get_db()
    c = conn.cursor()
    if round_number:
        c.execute("""
            SELECT ab.*, u.name, u.uid 
            FROM auction_bids ab 
            JOIN users u ON ab.user_id = u.user_id 
            WHERE ab.auction_id = ? AND ab.round_number = ? 
            ORDER BY ab.amount DESC
        """, (auction_id, round_number))
    else:
        c.execute("""
            SELECT ab.*, u.name, u.uid 
            FROM auction_bids ab 
            JOIN users u ON ab.user_id = u.user_id 
            WHERE ab.auction_id = ? 
            ORDER BY ab.round_number DESC, ab.amount DESC
        """, (auction_id,))
    bids = c.fetchall()
    conn.close()
    return bids

def get_user_bid_in_round(auction_id, user_id, round_number):
    """Получает ставку пользователя в раунде"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM auction_bids WHERE auction_id = ? AND user_id = ? AND round_number = ?", 
              (auction_id, user_id, round_number))
    bid = c.fetchone()
    conn.close()
    return bid

def get_user_position_in_auction(auction_id, user_id, round_number):
    """Получает позицию пользователя в аукционе"""
    bids = get_auction_bids(auction_id, round_number)
    for i, bid in enumerate(bids):
        if bid['user_id'] == user_id:
            return i + 1
    return None

def process_auction_round(auction_id, round_number):
    """Обрабатывает завершение раунда аукциона"""
    conn = get_db()
    c = conn.cursor()
    
    # Получаем информацию об аукционе и подарке
    auction = get_auction_by_id(auction_id)
    if not auction:
        conn.close()
        print(f"❌ Аукцион {auction_id} не найден")
        return
    
    gift = get_gift_by_id(auction['gift_id'])
    if not gift:
        conn.close()
        print(f"❌ Подарок для аукциона {auction_id} не найден")
        return
    
    # Проверяем корректность времени окончания
    if not auction['end_time']:
        print(f"❌ Время окончания аукциона {auction_id} не установлено")
        conn.close()
        return
    
    try:
        end_time = datetime.strptime(auction['end_time'], "%d.%m.%Y %H:%M:%S")
    except ValueError as e:
        print(f"❌ Ошибка парсинга времени окончания аукциона {auction_id}: {e}")
        conn.close()
        return
    
    winners_count = gift['auction_winners_count']
    
    # Получаем топ ставки
    bids = get_auction_bids(auction_id, round_number)
    
    winners = []
    losers = []
    
    # Определяем победителей и проигравших
    for i, bid in enumerate(bids):
        if i < winners_count:
            winners.append(bid)
            c.execute("UPDATE auction_bids SET is_winner = 1 WHERE bid_id = ?", (bid['bid_id'],))
        else:
            losers.append(bid)
    
    # Выдаем подарки победителям
    for winner in winners:
        serial_number = None
        c.execute("""
            INSERT INTO user_gifts (user_id, gift_name, gift_image, date, is_nft, serial_number, issued_by, issuer_username) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (winner['user_id'], gift['name'], gift['image'], datetime.now().strftime("%d.%m.%Y %H:%M:%S"), 
              0, serial_number, gift['issued_by'], gift['issuer_username']))
        
        # Отправляем уведомление победителю
        send_telegram_notification(
            winner['user_id'],
            f"🎉 *Поздравляем! Вы выиграли в аукционе!*\n\n"
            f"🎁 *{gift['name']}*\n"
            f"🏆 Раунд: *{round_number}*\n"
            f"💰 Ваша ставка: *{winner['amount']}* ⭐\n"
            f"📊 Ваше место: *{winners.index(winner) + 1}*\n\n"
            f"Подарок добавлен в вашу коллекцию!"
        )
    
    # Отправляем уведомление в канал о завершении раунда
    try:
        winners_text = "\n".join([f"{i+1}. {winner['name']} - {winner['amount']} ⭐" for i, winner in enumerate(winners)])
        message = f"🏁 *Раунд {round_number} завершен!*\n\n" \
                 f"🎁 *{gift['name']}*\n\n" \
                 f"🏆 *Победители раунда {round_number}:*\n" \
                 f"{winners_text}\n\n" \
                 f"✨ Поздравляем победителей!"
                 
        send_channel_notification(message)
    except Exception as e:
        print(f"❌ Ошибка отправки уведомления о завершении раунда: {e}")
    
    # Переносим ставки проигравших в следующий раунд (только тех, кто не выиграл)
    next_round = round_number + 1
    if next_round <= gift['auction_rounds']:
        for loser in losers:
            c.execute("""
                INSERT INTO auction_bids (auction_id, user_id, round_number, amount, bid_time)
                VALUES (?, ?, ?, ?, ?)
            """, (auction_id, loser['user_id'], next_round, loser['amount'], datetime.now().strftime("%d.%m.%Y %H:%M:%S")))
            
            # Уведомляем о переносе ставки
            send_telegram_notification(
                loser['user_id'],
                f"🔄 *Ваша ставка перенесена в следующий раунд!*\n\n"
                f"🎁 *{gift['name']}*\n"
                f"💰 Ваша ставка: *{loser['amount']}* ⭐\n"
                f"🎯 Следующий раунд: *{next_round}*\n\n"
                f"Удачи в следующем раунде!"
            )
    else:
        # Возвращаем средства проигравшим в последнем раунде
        for loser in losers:
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (loser['amount'], loser['user_id']))
            
            send_telegram_notification(
                loser['user_id'],
                f"💸 *Средства возвращены!*\n\n"
                f"🎁 *{gift['name']}*\n"
                f"💰 Возвращено: *{loser['amount']}* ⭐\n"
                f"📊 К сожалению, вы не выиграли в аукционе.\n\n"
                f"Средства возвращены на ваш баланс."
            )
    
    # Обновляем текущий раунд
    if next_round <= gift['auction_rounds']:
        c.execute("UPDATE auctions SET current_round = ? WHERE auction_id = ?", (next_round, auction_id))
        
        # Запускаем следующий раунд
        start_time = datetime.now()
        end_time = start_time + timedelta(minutes=gift['auction_duration'])
        
        c.execute("UPDATE auctions SET start_time = ?, end_time = ? WHERE auction_id = ?", 
                 (start_time.strftime("%d.%m.%Y %H:%M:%S"), end_time.strftime("%d.%m.%Y %H:%M:%S"), auction_id))
        
        # Уведомляем о начале нового раунда
        send_channel_notification(
            f"⚡ *Начался новый раунд аукциона!*\n\n"
            f"🎁 *{gift['name']}*\n"
            f"🎯 Раунд: *{next_round}*\n"
            f"⏰ Завершение: *{end_time.strftime('%d.%m.%Y %H:%M')}*\n"
            f"🏆 Победителей: *{winners_count}*\n\n"
            f"✨ Участвуйте: @VortexMarketBot"
        )
    else:
        # Завершаем аукцион
        c.execute("UPDATE auctions SET status = 'completed' WHERE auction_id = ?", (auction_id,))
        
        # Устанавливаем stock = 0 для аукционного подарка
        c.execute("UPDATE gifts SET stock = 0 WHERE gift_id = ?", (gift['gift_id'],))
        
        send_channel_notification(
            f"🏁 *Аукцион завершен!*\n\n"
            f"🎁 *{gift['name']}*\n"
            f"✅ Все раунды завершены\n"
            f"🏆 Победители получили свои подарки!\n\n"
            f"✨ Следите за новыми аукционами: @VortexMarketBot"
        )
    
    conn.commit()
    conn.close()

def start_auction_scheduler():
    """Запускает планировщик для проверки аукционов"""
    def check_auctions():
        while True:
            try:
                conn = get_db()
                c = conn.cursor()
                
                # Проверяем активные аукционы
                c.execute("SELECT * FROM auctions WHERE status = 'active'")
                active_auctions = c.fetchall()
                
                current_time = datetime.now()
                
                for auction in active_auctions:
                    # Проверяем наличие времени окончания
                    if not auction['end_time']:
                        print(f"⚠️ Аукцион {auction['auction_id']} без времени окончания")
                        continue
                    
                    try:
                        end_time = datetime.strptime(auction['end_time'], "%d.%m.%Y %H:%M:%S")
                    except ValueError as e:
                        print(f"❌ Ошибка парсинга времени для аукциона {auction['auction_id']}: {e}")
                        continue
                    
                    if current_time >= end_time:
                        print(f"🔄 Обработка завершения раунда для аукциона {auction['auction_id']}")
                        process_auction_round(auction['auction_id'], auction['current_round'])
                
                conn.close()
                
            except Exception as e:
                print(f"❌ Ошибка в планировщике аукционов: {e}")
            
            time.sleep(60)  # Проверяем каждую минуту
    
    scheduler_thread = threading.Thread(target=check_auctions)
    scheduler_thread.daemon = True
    scheduler_thread.start()

# Запускаем планировщик аукционов
start_auction_scheduler()

# --- HTML ШАБЛОНЫ ---

BASE_STYLES = '''
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
    
    :root {
        --primary: #6366F1;
        --primary-dark: #4F46E5;
        --primary-light: #8B5CF6;
        --secondary: #F59E0B;
        --secondary-dark: #D97706;
        --accent: #10B981;
        --danger: #EF4444;
        --dark: #0F172A;
        --darker: #020617;
        --light: #F8FAFC;
        --gray: #64748B;
        --gray-light: #E2E8F0;
        --glass: rgba(255, 255, 255, 0.05);
        --glass-border: rgba(255, 255, 255, 0.1);
        --shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
        --gradient: linear-gradient(135deg, var(--primary) 0%, var(--primary-light) 100%);
    }
    
    * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }
    
    body {
        background: linear-gradient(135deg, var(--darker) 0%, var(--dark) 100%);
        font-family: 'Inter', sans-serif;
        color: var(--light);
        min-height: 100vh;
        user-select: none;
        line-height: 1.6;
    }
    
    .app-container {
        max-width: 1400px;
        margin: 0 auto;
        padding: 20px;
        min-height: 100vh;
    }
    
    /* Header Styles */
    .header {
        background: var(--glass);
        backdrop-filter: blur(20px);
        border: 1px solid var(--glass-border);
        border-radius: 24px;
        padding: 24px;
        margin-bottom: 24px;
        box-shadow: var(--shadow);
        position: relative;
        overflow: hidden;
    }
    
    .header::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 1px;
        background: linear-gradient(90deg, transparent, var(--primary), transparent);
    }
    
    .user-info {
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 16px;
    }
    
    .user-main {
        display: flex;
        align-items: center;
        gap: 16px;
    }
    
    .user-avatar {
        width: 64px;
        height: 64px;
        background: var(--gradient);
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 24px;
        font-weight: 600;
        color: white;
        box-shadow: 0 8px 32px rgba(99, 102, 241, 0.3);
    }
    
    .user-details h1 {
        font-size: 24px;
        font-weight: 700;
        margin-bottom: 4px;
    }
    
    .balance {
        font-size: 28px;
        font-weight: 800;
        color: var(--secondary);
        text-shadow: 0 2px 20px rgba(245, 158, 11, 0.4);
    }

    .balance-container {
        display: flex;
        align-items: center;
        gap: 10px;
    }
    
    .top-up-btn {
        width: 30px;
        height: 30px;
        padding: 0;
        font-size: 18px;
        line-height: 1;
        border-radius: 50%;
        flex-shrink: 0;
        background: var(--accent);
        color: white;
        border: none;
        cursor: pointer;
        transition: transform 0.2s ease;
    }
    
    .top-up-btn:hover {
        transform: scale(1.1);
        box-shadow: 0 4px 10px rgba(16, 185, 129, 0.4);
    }

    .modal {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.7);
        display: none;
        justify-content: center;
        align-items: center;
        z-index: 2000;
        opacity: 0;
        transition: opacity 0.3s ease;
    }

    .modal.show {
        display: flex;
        opacity: 1;
    }

    .modal-content {
        background: var(--dark);
        padding: 30px;
        border-radius: 20px;
        max-width: 450px;
        width: 90%;
        box-shadow: var(--shadow);
        border: 1px solid var(--glass-border);
        animation: fadeInUp 0.3s ease-out;
    }

    .modal-header {
        font-size: 20px;
        font-weight: 700;
        margin-bottom: 20px;
        text-align: center;
    }

    .option-card {
        background: var(--glass);
        padding: 20px;
        border-radius: 16px;
        margin-bottom: 15px;
        cursor: pointer;
        transition: all 0.2s ease;
        border: 1px solid transparent;
    }

    .option-card:hover {
        background: rgba(99, 102, 241, 0.1);
        border-color: var(--primary);
        transform: translateY(-2px);
    }

    .option-card h4 {
        margin-bottom: 5px;
        font-size: 16px;
        font-weight: 600;
    }

    .option-card p {
        font-size: 12px;
        color: var(--gray);
    }

    .modal-back-btn {
        margin-top: 20px;
        width: 100%;
    }
    .stars-input-group {
        display: flex;
        gap: 10px;
        margin-bottom: 15px;
    }
    .stars-input-group input {
        flex-grow: 1;
    }
    .nft-info-box {
        padding: 15px;
        border-radius: 12px;
        background: rgba(245, 158, 11, 0.1);
        border: 1px solid var(--secondary);
        font-size: 14px;
        margin-bottom: 20px;
    }
    .nft-address-display {
        word-break: break-all;
        font-family: monospace;
        background: rgba(0, 0, 0, 0.2);
        padding: 8px;
        border-radius: 8px;
        margin-top: 10px;
        font-size: 12px;
        color: var(--secondary);
    }
    
    /* Navigation Styles */
    .nav {
        display: flex;
        gap: 12px;
        margin-bottom: 32px;
        flex-wrap: wrap;
        position: sticky;
        top: 0;
        z-index: 100;
        background: rgba(15, 23, 42, 0.8);
        backdrop-filter: blur(20px);
        padding: 16px;
        border-radius: 16px;
        border: 1px solid var(--glass-border);
    }
    
    .nav-item {
        background: var(--glass);
        border: 1px solid var(--glass-border);
        padding: 16px 24px;
        border-radius: 16px;
        text-decoration: none;
        color: var(--light);
        font-weight: 600;
        transition: all 0.3s ease;
        display: flex;
        align-items: center;
        gap: 8px;
        backdrop-filter: blur(10px);
    }
    
    .nav-item:hover {
        background: rgba(99, 102, 241, 0.1);
        border-color: var(--primary);
        transform: translateY(-2px);
        box-shadow: 0 8px 32px rgba(99, 102, 241, 0.2);
    }
    
    .nav-item.active {
        background: var(--gradient);
        border-color: var(--primary);
    }
    
    /* Section Headers */
    .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 24px;
    }
    
    .section-title {
        font-size: 24px;
        font-weight: 700;
        position: relative;
    }
    
    .section-title::after {
        content: '';
        position: absolute;
        bottom: -8px;
        left: 0;
        width: 40px;
        height: 3px;
        background: var(--gradient);
        border-radius: 2px;
    }
    
    /* Grid Layout */
    .grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
        gap: 20px;
        margin-bottom: 32px;
    }
    
    /* Card Styles */
    .card {
        background: var(--glass);
        backdrop-filter: blur(20px);
        border: 1px solid var(--glass-border);
        border-radius: 16px;
        padding: 16px;
        transition: all 0.3s ease;
        position: relative;
        overflow: hidden;
        animation: fadeInUp 0.6s ease-out;
        
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    
    .card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 4px;
        background: var(--gradient);
    }
    
    .card:hover {
        transform: translateY(-8px) scale(1.02);
        box-shadow: var(--shadow);
        border-color: rgba(99, 102, 241, 0.3);
    }
    
    .card-media {
        width: 100%;
        height: 160px;
        border-radius: 12px;
        overflow: hidden;
        margin-bottom: 12px;
        background: rgba(0, 0, 0, 0.3);
        display: flex;
        align-items: center;
        justify-content: center;
        transition: transform 0.3s ease;
    }
    
    .card:hover .card-media {
        transform: scale(1.05);
    }
    
    .card-media img,
    .card-media video {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }
    
    .auction-media {
        width: 100%;
        max-height: 400px;
        border-radius: 16px;
        overflow: hidden;
        margin-bottom: 20px;
        background: rgba(0, 0, 0, 0.3);
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    .auction-media img,
    .auction-media video {
        width: 100%;
        height: 100%;
        object-fit: contain;
        max-height: 400px;
    }
    
    .card-content {
        flex-grow: 1;
        display: flex;
        flex-direction: column;
    }
    
    .card-title {
        font-size: 16px;
        font-weight: 700;
        margin-bottom: 8px;
        text-align: center;
    }
    
    /* Badges */
    .badges {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-bottom: 12px;
        justify-content: center;
    }
    
    .badge {
        padding: 4px 8px;
        border-radius: 12px;
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    .badge.serial {
        background: linear-gradient(135deg, var(--primary-light) 0%, #A855F7 100%);
        color: white;
    }
    
    .badge.tester {
        background: linear-gradient(135deg, #F59E0B 0%, #D97706 100%);
        color: white;
    }
    
    .badge.auction {
        background: linear-gradient(135deg, #EF4444 0%, #DC2626 100%);
        color: white;
    }
    
    /* Buttons */
    .btn-group {
        display: flex;
        flex-direction: column;
        gap: 8px;
        margin-top: auto; 
        padding-top: 10px;
    }
    
    .btn {
        padding: 10px 12px;
        border: none;
        border-radius: 10px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s ease;
        text-align: center;
        font-size: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
    }
    
    .btn-primary {
        background: var(--gradient);
        color: white;
    }
    
    .btn-primary:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 32px rgba(99, 102, 241, 0.4);
    }
    
    .btn-secondary {
        background: rgba(245, 158, 11, 0.1);
        color: var(--secondary);
        border: 1px solid rgba(245, 158, 11, 0.3);
    }
    
    .btn-secondary:hover {
        background: rgba(245, 158, 11, 0.2);
        transform: translateY(-2px);
    }
    
    .btn-danger {
        background: rgba(239, 68, 68, 0.1);
        color: var(--danger);
        border: 1px solid rgba(239, 68, 68, 0.3);
    }
    
    .btn-danger:hover {
        background: rgba(239, 68, 68, 0.2);
        transform: translateY(-2px);
    }
    
    .btn-disabled {
        background: rgba(100, 116, 139, 0.1);
        color: var(--gray);
        border: 1px solid rgba(100, 116, 139, 0.3);
        cursor: not-allowed;
    }
    
    .btn-disabled:hover {
        transform: none;
        box-shadow: none;
    }
    
    /* Price and Info */
    .price {
        font-size: 16px;
        font-weight: 700;
        color: var(--secondary);
        text-align: center;
        margin: 8px 0;
    }
    
    .info {
        font-size: 12px;
        color: var(--gray);
        text-align: center;
        margin-bottom: 12px;
    }
    
    .issuer-info {
        font-size: 11px;
        color: var(--primary-light);
        text-align: center;
        margin-bottom: 8px;
    }
    
    .issuer-link {
        color: var(--primary-light);
        text-decoration: none;
        transition: color 0.3s ease;
    }
    
    .issuer-link:hover {
        color: var(--primary);
        text-decoration: underline;
    }
    
    /* Empty State */
    .empty-state {
        text-align: center;
        padding: 80px 20px;
        color: var(--gray);
    }
    
    .empty-icon {
        font-size: 64px;
        margin-bottom: 16px;
        opacity: 0.5;
    }
    
    .empty-text {
        font-size: 18px;
        margin-bottom: 8px;
    }
    
    .empty-subtext {
        color: var(--gray);
    }
    
    /* Admin Styles */
    .admin-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
        gap: 24px;
    }
    
    .form-group {
        margin-bottom: 20px;
    }
    
    .form-label {
        display: block;
        margin-bottom: 8px;
        font-weight: 600;
        color: var(--light);
    }
    
    .form-input {
        width: 100%;
        padding: 12px 16px;
        border-radius: 12px;
        border: 1px solid var(--glass-border);
        background: rgba(0, 0, 0, 0.3);
        color: var(--light);
        font-size: 14px;
        transition: all 0.3s ease;
    }
    
    .form-input:focus {
        outline: none;
        border-color: var(--primary);
        box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
    }
    
    /* Ad Banner */
    .ad-banner {
        background: linear-gradient(135deg, var(--primary) 0%, var(--primary-light) 100%);
        padding: 16px;
        border-radius: 16px;
        margin-bottom: 24px;
        text-align: center;
        font-weight: 600;
        position: relative;
        overflow: hidden;
    }
    
    .ad-banner::before {
        content: '✨';
        margin-right: 8px;
    }
    
    /* Auction Banner */
    .auction-banner {
        background: linear-gradient(135deg, #EF4444 0%, #DC2626 100%);
        padding: 20px;
        border-radius: 16px;
        margin-bottom: 24px;
        text-align: center;
        font-weight: 600;
        position: relative;
        overflow: hidden;
        animation: pulse 2s infinite;
    }
    
    .auction-banner::before {
        content: '⚡';
        margin-right: 8px;
    }
    
    /* Auction Info */
    .auction-info {
        background: var(--glass);
        border: 1px solid var(--glass-border);
        border-radius: 16px;
        padding: 20px;
        margin-bottom: 24px;
    }
    
    .auction-stats {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 16px;
        margin-bottom: 20px;
    }
    
    .stat-card {
        background: rgba(0, 0, 0, 0.2);
        padding: 16px;
        border-radius: 12px;
        text-align: center;
    }
    
    .stat-value {
        font-size: 24px;
        font-weight: 700;
        color: var(--secondary);
        margin-bottom: 4px;
    }
    
    .stat-label {
        font-size: 12px;
        color: var(--gray);
    }
    
    .bids-list {
        max-height: 300px;
        overflow-y: auto;
    }
    
    .bid-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px;
        border-bottom: 1px solid var(--glass-border);
    }
    
    .bid-item:last-child {
        border-bottom: none;
    }
    
    .bid-user {
        display: flex;
        align-items: center;
        gap: 8px;
    }
    
    .bid-amount {
        font-weight: 700;
        color: var(--secondary);
    }
    
    .bid-position {
        background: var(--primary);
        color: white;
        padding: 4px 8px;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 600;
    }
    
    /* Notification */
    .notification {
        position: fixed;
        top: 20px;
        right: 20px;
        background: var(--accent);
        color: white;
        padding: 12px 20px;
        border-radius: 12px;
        box-shadow: var(--shadow);
        z-index: 1000;
        transform: translateX(400px);
        opacity: 0;
        transition: all 0.5s cubic-bezier(0.68, -0.55, 0.265, 1.55);
        max-width: 300px;
        font-weight: 600;
    }
    
    .notification.show {
        transform: translateX(0);
        opacity: 1;
    }
    
    .notification.hide {
        transform: translateX(400px);
        opacity: 0;
    }
    
    /* Animations */
    @keyframes fadeInUp {
        from {
            opacity: 0;
            transform: translateY(30px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    
    @keyframes pulse {
        0% {
            transform: scale(1);
        }
        50% {
            transform: scale(1.05);
        }
        100% {
            transform: scale(1);
        }
    }
    
    @keyframes bounce {
        0%, 20%, 53%, 80%, 100% {
            transform: translateY(0);
        }
        40%, 43% {
            transform: translateY(-15px);
        }
        70% {
            transform: translateY(-7px);
        }
        90% {
            transform: translateY(-3px);
        }
    }
    
    .pulse {
        animation: pulse 2s infinite;
    }
    
    .bounce {
        animation: bounce 1s;
    }
    
    /* Responsive */
    @media (max-width: 768px) {
        .app-container {
            padding: 16px;
        }
        
        .grid {
            grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
            gap: 16px;
        }
        
        .user-info {
            flex-direction: column;
            text-align: center;
        }
        
        .user-main {
            flex-direction: column;
        }
        
        .nav {
            justify-content: center;
        }
        
        .admin-grid {
            grid-template-columns: 1fr;
        }
        
        .card-media {
            height: 140px;
        }
        
        .auction-media {
            max-height: 300px;
        }
        
        .notification {
            top: 10px;
            right: 10px;
            left: 10px;
            max-width: none;
        }
        
        .auction-stats {
            grid-template-columns: 1fr;
        }
    }
</style>
'''

PROFILE_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Профиль • Vortex Market</title>
    ''' + BASE_STYLES + '''
</head>
<body>
    <div class="app-container">
        {% if user.is_banned %}
        <div class="header" style="background: rgba(239, 68, 68, 0.1); border-color: var(--danger);">
            <div style="text-align: center; padding: 20px;">
                <div style="font-size: 48px; margin-bottom: 16px;">🚫</div>
                <h1 style="color: var(--danger); margin-bottom: 8px;">Аккаунт заблокирован</h1>
                <p style="color: var(--gray); margin-bottom: 8px;"><strong>Причина:</strong> {{ user.ban_reason }}</p>
                {% if user.ban_until and user.ban_until != 'permanent' %}
                <p style="color: var(--gray);"><strong>Разблокировка:</strong> {{ user.ban_until }}</p>
                {% else %}
                <p style="color: var(--gray);"><strong>Блокировка:</strong> Бессрочно</p>
                {% endif %}
            </div>
        </div>
        {% else %}
        <div class="header">
            <div class="user-info">
                <div class="user-main">
                    <div class="user-avatar">{{ user.name[0] }}</div>
                    <div class="user-details">
                        <h1>{{ user.name }}</h1>
                        <div class="balance-container">
                            <div class="balance">⭐ {{ "{:,}".format(user.balance).replace(",", " ") }}</div>
                            <button class="btn btn-primary top-up-btn" onclick="showTopUpModal()">
                                +
                            </button>
                        </div>
                    </div>
                </div>
                <div class="user-stats">
                    <div style="color: var(--gray);">Подарков: {{ user.gifts|length }}</div>
                </div>
            </div>
        </div>

        {% if ad_text %}
        <div class="ad-banner">{{ ad_text }}</div>
        {% endif %}

        <div class="nav">
            <a href="/profile?id={{ user.id }}" class="nav-item active">🎁 Мои подарки</a>
            <a href="/shop?id={{ user.id }}" class="nav-item">🛍️ Магазин</a>
            <a href="/market?id={{ user.id }}" class="nav-item">🏪 Маркет</a>
            <a href="/auction?id={{ user.id }}" class="nav-item">🎯 Аукцион</a>
            {% if user.is_admin %}
            <a href="/admin?id={{ user.id }}" class="nav-item">⚙️ Админ</a>
            {% endif %}
        </div>

        <div class="section-header">
            <h2 class="section-title">Коллекция подарков</h2>
            <div style="color: var(--gray);">{{ user.gifts|length }} items</div>
        </div>

        {% if user.gifts %}
        <div class="grid">
            {% for gift in user.gifts %}
            <div class="card">
                <div class="card-media">
                    {% if gift.image %}
                        {% if gift.image.endswith('.mp4') or gift.image.endswith('.mov') or gift.image.endswith('.avi') or gift.image.endswith('.webm') %}
                        <video autoplay loop muted playsinline>
                            <source src="{{ gift.image }}" type="video/mp4">
                        </video>
                        {% else %}
                        <img src="{{ gift.image }}" alt="{{ gift.name }}">
                        {% endif %}
                    {% else %}
                    <img src="https://via.placeholder.com/200x200/0F172A/64748B?text=🎁" alt="{{ gift.name }}">
                    {% endif %}
                </div>
                
                <div class="card-content">
                    <h3 class="card-title">
                        {% if gift.is_nft and gift.serial_number %}
                            {{ gift.name }} #{{ gift.serial_number }}
                        {% else %}
                            {{ gift.name }}
                        {% endif %}
                    </h3>

                    {% if gift.issuer_username %}
                    <div class="issuer-info">
                        Выпущен <a href="https://t.me/{{ gift.issuer_username|replace('@', '') }}" class="issuer-link" target="_blank">@{{ gift.issuer_username }}</a>
                    </div>
                    {% elif gift.issued_by %}
                    <div class="issuer-info">
                        Выпущен @{{ gift.issued_by }}
                    </div>
                    {% endif %}
                </div>

                <div class="btn-group">
                    {% if gift.status == 'unupgraded' %}
                        {% if gift.can_upgrade %}
                            <button class="btn btn-primary" onclick="upgrade({{ gift.id }})">
                                ⚡ Улучшить
                            </button>
                        {% endif %}
                        <button class="btn btn-secondary" onclick="burnGift({{ gift.id }})">
                            🔥 Сжечь за 85%
                        </button>
                    {% elif gift.status == 'upgraded' %}
                        {% if gift.is_nft %}
                            {% if gift.market_price > 0 %}
                                <div class="price">💰 {{ gift.market_price }} ⭐</div>
                                <button class="btn btn-secondary" onclick="changeMarketPrice({{ gift.id }})">
                                    📊 Изменить цену
                                </button>
                                <button class="btn btn-danger" onclick="removeFromMarket({{ gift.id }})">
                                    ❌ Снять с продажи
                                </button>
                            {% else %}
                                <button class="btn btn-secondary" onclick="sellToMarket({{ gift.id }})">
                                    💰 Продать
                                </button>
                                <button class="btn btn-primary" onclick="transferGift({{ gift.id }})">
                                    🎁 Передать
                                </button>
                            {% endif %}
                        {% else %}
                            <div class="info" style="color: var(--danger); font-weight: 600;">Нельзя продать.</div>
                            {% if gift.market_price == 0 %}
                                <button class="btn btn-primary" onclick="transferGift({{ gift.id }})">
                                    🎁 Передать
                                </button>
                            {% endif %}
                        {% endif %}
                    {% elif gift.status == 'on_market' %}
                        <div class="price">💰 {{ gift.market_price }} ⭐</div>
                        <button class="btn btn-secondary" onclick="changeMarketPrice({{ gift.id }})">
                            📊 Изменить цену
                        </button>
                        <button class="btn btn-danger" onclick="removeFromMarket({{ gift.id }})">
                            ❌ Снять с продажи
                        </button>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        </div>
        {% else %}
        <div class="empty-state">
            <div class="empty-icon">🎁</div>
            <div class="empty-text">Коллекция пуста</div>
            <div class="empty-subtext">Приобретите подарки в магазине</div>
            <a href="/shop?id={{ user.id }}" class="btn btn-primary" style="margin-top: 20px; display: inline-block; text-decoration: none;">
                🛍️ Перейти в магазин
            </a>
        </div>
        {% endif %}
        {% endif %}
    </div>

    <div id="notification" class="notification"></div>
    
    <!-- МОДАЛЬНОЕ ОКНО ДЛЯ ПОПОЛНЕНИЯ -->
    <div id="topUpModal" class="modal" onclick="closeTopUpModal(event)">
        <div class="modal-content" id="modalContent">
            
            <div id="topUpStep1">
                <div class="modal-header">Выберите способ пополнения</div>

                <div class="option-card" onclick="showStarsStep()">
                    <h4>💳 Stars (Мгновенно)</h4>
                    <p>Пополнение через тестовый токен Telegram Stars. Макс. 100,000 ⭐.</p>
                </div>

                <div class="option-card" onclick="showNftStep()">
                    <h4>🖼️ NFT (до 24 часов)</h4>
                    <p>Отправьте NFT и получите {{ "{:,}".format(NFT_VALUE_IN_STARS).replace(",", " ") }} ⭐ за NFT на баланс.</p>
                </div>
            </div>

            <div id="topUpStepStars" style="display: none;">
                <div class="modal-header">Пополнение через Stars</div>
                <p style="margin-bottom: 10px;">Введите сумму (Stars = ⭐). Макс. 100,000:</p>
                
                <div class="stars-input-group">
                    <input type="number" id="starsAmount" class="form-input" min="1" max="100000" value="100" placeholder="Сумма Stars" required>
                </div>

                <button class="btn btn-primary" onclick="processStarsTopUp()">
                    ✅ Создать инвойс
                </button>
                <button class="btn btn-secondary modal-back-btn" onclick="showStep1()">
                    ⬅️ Назад
                </button>
            </div>
            
            <div id="topUpStepNft" style="display: none;">
                <div class="modal-header">Пополнение через NFT</div>
                
                <div class="nft-info-box">
                    <p>⚠️ Внимание: Отправьте NFT на указанный юз. После проверки (до 24 часов) вы получите **{{ "{:,}".format(NFT_VALUE_IN_STARS).replace(",", " ") }} ⭐** за NFT (можно несколько NFT).</p>
                    <p style="margin-top: 10px;">Юз для отправки NFT:</p>
                    <div id="nftAddressDisplay" class="nft-address-display">{{ NFT_RECEIVING_ADDRESS }}</div>
                </div>
                
                <button class="btn btn-primary" onclick="processNftTopUp()">
                    🖼️ Я отправил NFT
                </button>
                <button class="btn btn-secondary modal-back-btn" onclick="showStep1()">
                    ⬅️ Назад
                </button>
            </div>

        </div>
    </div>

    {% if not user.is_banned %}
    <script>
        const userId = "{{ user.id }}";
        
        const modal = document.getElementById('topUpModal');
        const step1 = document.getElementById('topUpStep1');
        const stepStars = document.getElementById('topUpStepStars');
        const stepNft = document.getElementById('topUpStepNft');
        const nftValueInStars = {{ NFT_VALUE_IN_STARS }};
        const maxStarsAmount = 100000;

        function showTopUpModal() {
            showStep1();
            modal.classList.add('show');
        }

        function closeTopUpModal(event) {
            if (event && event.target === modal) {
                modal.classList.remove('show');
            } else if (!event) {
                modal.classList.remove('show');
            }
        }
        
        function showStep1() {
            step1.style.display = 'block';
            stepStars.style.display = 'none';
            stepNft.style.display = 'none';
        }

        function showStarsStep() {
            step1.style.display = 'none';
            stepStars.style.display = 'block';
        }

        function showNftStep() {
            step1.style.display = 'none';
            stepNft.style.display = 'block';
        }

        async function processStarsTopUp() {
            let amount = parseInt(document.getElementById('starsAmount').value);
            
            if (isNaN(amount) || amount < 1 || amount > maxStarsAmount) {
                showNotification(`Неверная сумма. Максимум ${maxStarsAmount} ⭐`, 'error');
                return;
            }

            showNotification('Создание инвойса...', 'success');
            
            try {
                const response = await fetch(`/topup/stars?id=${userId}&amount=${amount}`, { method: 'POST' });
                const data = await response.json();
                
                if (data.success) {
                    window.open(data.invoice_link, '_blank');
                    showNotification('Инвойс создан. Перейдите по ссылке для оплаты.', 'success');
                    closeTopUpModal();
                } else {
                    showNotification(data.msg, 'error');
                }
            } catch (error) {
                showNotification('Ошибка сети при создании инвойса', 'error');
            }
        }

        async function processNftTopUp() {
            const confirmMsg = `Вы уверены, что отправили NFT на адрес {{ NFT_RECEIVING_ADDRESS }}? Вам будет начислено ${nftValueInStars.toLocaleString('ru-RU').replace(',', ' ')} ⭐ после проверки (до 24ч).`;
            const confirmation = window.confirm(confirmMsg);
            
            if (!confirmation) return;
            
            try {
                const response = await fetch(`/topup/nft?id=${userId}`, { method: 'POST' });
                const data = await response.json();
                
                if (data.success) {
                    showNotification(data.msg, 'success');
                    closeTopUpModal();
                } else {
                    showNotification(data.msg, 'error');
                }
            } catch (error) {
                showNotification('Ошибка сети при регистрации NFT пополнения', 'error');
            }
        }

        function showNotification(message, type = 'success') {
            const notification = document.getElementById('notification');
            notification.textContent = message;
            notification.className = 'notification show';
            
            if (type === 'error') {
                notification.style.background = '#EF4444';
            } else {
                notification.style.background = '#10B981';
            }
            
            setTimeout(() => {
                notification.className = 'notification hide';
            }, 3000);
        }

        async function upgrade(id) {
            try {
                const response = await fetch(`/upgrade/${id}?id=${userId}`, { method: 'POST' });
                const data = await response.json();
                
                if (data.success) {
                    showNotification(data.msg);
                    setTimeout(() => location.reload(), 1000);
                } else {
                    showNotification(data.msg, 'error');
                }
            } catch (error) {
                showNotification('Ошибка при улучшении', 'error');
            }
        }
        
        async function burnGift(id) {
            const confirmation = window.confirm("Вы уверены, что хотите сжечь этот подарок? Вы получите 85% от его стоимости на баланс.");
            if (!confirmation) return;

            try {
                const response = await fetch(`/burn_gift/${id}?id=${userId}`, { method: 'POST' });
                const data = await response.json();
                
                if (data.success) {
                    showNotification(data.msg);
                    setTimeout(() => location.reload(), 1000);
                } else {
                    showNotification(data.msg, 'error');
                }
            } catch (error) {
                showNotification('Ошибка при сжигании подарка', 'error');
            }
        }
        
        async function sellToMarket(id) {
            let price = prompt("Укажите цену продажи (125-250000):");
            price = parseInt(price);
            if (isNaN(price) || price < 125 || price > 250000) {
                showNotification('Неверная цена', 'error');
                return;
            }

            try {
                const response = await fetch(`/market/sell/${id}?id=${userId}&price=${price}`, { method: 'POST' });
                const data = await response.json();
                
                if (data.success) {
                    showNotification(data.msg);
                    setTimeout(() => location.reload(), 1000);
                } else {
                    showNotification(data.msg, 'error');
                }
            } catch (error) {
                showNotification('Ошибка при выставлении на продажу', 'error');
            }
        }

        async function changeMarketPrice(id) {
            let newPrice = prompt("Новая цена (125-250000):");
            newPrice = parseInt(newPrice);
            if (isNaN(newPrice) || newPrice < 125 || newPrice > 250000) {
                showNotification('Неверная цена', 'error');
                return;
            }

            try {
                const response = await fetch(`/market/change_price/${id}?id=${userId}&price=${newPrice}`, { method: 'POST' });
                const data = await response.json();
                
                if (data.success) {
                    showNotification(data.msg);
                    setTimeout(() => location.reload(), 1000);
                } else {
                    showNotification(data.msg, 'error');
                }
            } catch (error) {
                showNotification('Ошибка при изменении цены', 'error');
            }
        }

        async function removeFromMarket(id) {
            try {
                const response = await fetch(`/market/remove/${id}?id=${userId}`, { method: 'POST' });
                const data = await response.json();
                
                if (data.success) {
                    showNotification(data.msg);
                    setTimeout(() => location.reload(), 1000);
                } else {
                    showNotification(data.msg, 'error');
                }
            } catch (error) {
                showNotification('Ошибка при снятии с продажи', 'error');
            }
        }
        
        async function transferGift(id) {
            let recipient = prompt("Введите ID получателя в Telegram (например, 5002745060):");
            if (!recipient) return;
            
            try {
                const response = await fetch(`/transfer_gift/${id}?id=${userId}&recipient=${recipient}`, { method: 'POST' });
                const data = await response.json();
                
                if (data.success) {
                    showNotification(data.msg);
                    setTimeout(() => location.reload(), 1000);
                } else {
                    showNotification(data.msg, 'error');
                }
            } catch (error) {
                showNotification('Ошибка при передаче подарка', 'error');
            }
        }

        // Закрытие модального окна при нажатии на Escape
        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') {
                closeTopUpModal();
            }
        });
    </script>
    {% endif %}
</body>
</html>'''

SHOP_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Магазин • Vortex Market</title>
    ''' + BASE_STYLES + '''
</head>
<body>
    <div class="app-container">
        {% if user.is_banned %}
        <div class="header" style="background: rgba(239, 68, 68, 0.1); border-color: var(--danger);">
            <div style="text-align: center; padding: 20px;">
                <div style="font-size: 48px; margin-bottom: 16px;">🚫</div>
                <h1 style="color: var(--danger); margin-bottom: 8px;">Аккаунт заблокирован</h1>
                <p style="color: var(--gray); margin-bottom: 8px;"><strong>Причина:</strong> {{ user.ban_reason }}</p>
                {% if user.ban_until and user.ban_until != 'permanent' %}
                <p style="color: var(--gray);"><strong>Разблокировка:</strong> {{ user.ban_until }}</p>
                {% else %}
                <p style="color: var(--gray);"><strong>Блокировка:</strong> Бессрочно</p>
                {% endif %}
            </div>
        </div>
        {% else %}
        <div class="header">
            <div class="user-info">
                <div class="user-main">
                    <div class="user-avatar">🛍️</div>
                    <div class="user-details">
                        <h1>Магазин подарков</h1>
                        <div style="color: var(--gray);">Доступные товары</div>
                    </div>
                </div>
                <div class="user-stats">
                    <div class="balance">⭐ {{ "{:,}".format(user.balance).replace(",", " ") }}</div>
                </div>
            </div>
        </div>

        {% if ad_text %}
        <div class="ad-banner">{{ ad_text }}</div>
        {% endif %}

        <div class="nav">
            <a href="/profile?id={{ user.id }}" class="nav-item">🎁 Мои подарки</a>
            <a href="/shop?id={{ user.id }}" class="nav-item active">🛍️ Магазин</a>
            <a href="/market?id={{ user.id }}" class="nav-item">🏪 Маркет</a>
            <a href="/auction?id={{ user.id }}" class="nav-item">🎯 Аукцион</a>
            {% if user.is_admin %}
            <a href="/admin?id={{ user.id }}" class="nav-item">⚙️ Админ</a>
            {% endif %}
        </div>

        <div class="section-header">
            <h2 class="section-title">Все подарки</h2>
            <div style="color: var(--gray);">{{ gifts|length }} items</div>
        </div>

        {% if gifts %}
        <div class="grid">
            {% for gift in gifts %}
            <div class="card">
                <div class="card-media">
                    {% if gift.image %}
                        {% if gift.image.endswith('.mp4') or gift.image.endswith('.mov') or gift.image.endswith('.avi') or gift.image.endswith('.webm') %}
                        <video autoplay loop muted playsinline>
                            <source src="{{ gift.image }}" type="video/mp4">
                        </video>
                        {% else %}
                        <img src="{{ gift.image }}" alt="{{ gift.name }}">
                        {% endif %}
                    {% else %}
                    <img src="https://via.placeholder.com/200x200/0F172A/64748B?text=🎁" alt="{{ gift.name }}">
                    {% endif %}
                </div>
                
                <div class="card-content">
                    <h3 class="card-title">{{ gift.name }}</h3>
                    
                    <div class="badges">
                        {% if gift.for_testers %}
                        <div class="badge tester">ДЛЯ ТЕСТЕРОВ</div>
                        {% endif %}
                        {% if gift.is_auction %}
                        <div class="badge auction">АУКЦИОН</div>
                        {% endif %}
                    </div>

                    {% if gift.issuer_username %}
                    <div class="issuer-info">
                        Выпущен <a href="https://t.me/{{ gift.issuer_username|replace('@', '') }}" class="issuer-link" target="_blank">@{{ gift.issuer_username }}</a>
                    </div>
                    {% elif gift.issued_by %}
                    <div class="issuer-info">
                        Выпущен @{{ gift.issued_by }}
                    </div>
                    {% endif %}

                    {% if not gift.is_auction %}
                    <div class="price">{{ gift.price }} ⭐</div>
                    {% endif %}
                    <div class="info">
                        {% if gift.is_auction %}
                            <span style="color: var(--danger); font-weight: 600;">🎯 АУКЦИОН</span>
                        {% elif gift.stock == -1 %}
                            ∞ В наличии
                        {% elif gift.stock > 0 %}
                            В наличии: {{ gift.stock }} шт.
                        {% else %}
                            <span style="color: var(--danger);">Распродано</span>
                        {% endif %}
                    </div>
                </div>

                <div class="btn-group">
                    {% if gift.stock != 0 or gift.stock == -1 %} 
                        {% set can_buy = user.balance >= gift.price %}
                        {% set is_admin = user.is_admin %}
                        {% set is_tester_gift = gift.for_testers %}
                        {% set is_auction_gift = gift.is_auction %}
                        
                        {% if is_tester_gift and not is_admin %}
                            <button class="btn btn-disabled" disabled title="Только для тестеров">
                                🔒 Только для тестеров
                            </button>
                        {% elif is_auction_gift %}
                            <button class="btn btn-primary" onclick="location.href='/auction?id={{ user.id }}'">
                                🎯 Участвовать в аукционе
                            </button>
                        {% elif gift.stock == -1 %}
                            <button class="btn btn-primary" onclick="buyUnlimitedGift({{ gift.gift_id }})" 
                                {% if not can_buy %}disabled{% endif %}>
                                🎁 Купить и Отправить
                            </button>
                        {% else %}
                            <button class="btn btn-primary" onclick="buyGift({{ gift.gift_id }})" 
                                {% if not can_buy %}disabled{% endif %}>
                                🛒 Купить сейчас
                            </button>
                        {% endif %}
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        </div>
        {% else %}
        <div class="empty-state">
            <div class="empty-icon">🏪</div>
            <div class="empty-text">Магазин пуст</div>
            <div class="empty-subtext">Скоро появятся новые подарки</div>
        </div>
        {% endif %}
        {% endif %}
    </div>

    <div id="notification" class="notification"></div>

    {% if not user.is_banned %}
    <script>
        const userId = "{{ user.id }}";
        const myUserId = "{{ user.user_id }}";
        
        function showNotification(message, type = 'success') {
            const notification = document.getElementById('notification');
            notification.textContent = message;
            notification.className = 'notification show';
            
            if (type === 'error') {
                notification.style.background = '#EF4444';
            } else {
                notification.style.background = '#10B981';
            }
            
            setTimeout(() => {
                notification.className = 'notification hide';
            }, 3000);
        }

        async function buyGift(giftId) {
            try {
                const response = await fetch(`/buy/${giftId}?id=${userId}`, { method: 'POST' });
                const data = await response.json();
                
                if (data.success) {
                    showNotification(data.msg);
                    setTimeout(() => location.reload(), 1000);
                } else {
                    showNotification(data.msg, 'error');
                }
            } catch (error) {
                showNotification('Ошибка при покупке', 'error');
            }
        }
        
        async function buyUnlimitedGift(giftId) {
            let recipientId = prompt(`Введите ID получателя (или свой ID: ${myUserId}) для отправки подарка:`);
            if (!recipientId) return;

            try {
                const response = await fetch(`/buy/${giftId}?id=${userId}&recipient_uid=${recipientId}`, { method: 'POST' });
                const data = await response.json();
                
                if (data.success) {
                    showNotification(data.msg);
                    setTimeout(() => location.reload(), 1000);
                } else {
                    showNotification(data.msg, 'error');
                }
            } catch (error) {
                showNotification('Ошибка при покупке', 'error');
            }
        }
    </script>
    {% endif %}
</body>
</html>'''

MARKET_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Маркет • Vortex Market</title>
    ''' + BASE_STYLES + '''
</head>
<body>
    <div class="app-container">
        {% if user.is_banned %}
        <div class="header" style="background: rgba(239, 68, 68, 0.1); border-color: var(--danger);">
            <div style="text-align: center; padding: 20px;">
                <div style="font-size: 48px; margin-bottom: 16px;">🚫</div>
                <h1 style="color: var(--danger); margin-bottom: 8px;">Аккаунт заблокирован</h1>
                <p style="color: var(--gray); margin-bottom: 8px;"><strong>Причина:</strong> {{ user.ban_reason }}</p>
                {% if user.ban_until and user.ban_until != 'permanent' %}
                <p style="color: var(--gray);"><strong>Разблокировка:</strong> {{ user.ban_until }}</p>
                {% else %}
                <p style="color: var(--gray);"><strong>Блокировка:</strong> Бессрочно</p>
                {% endif %}
            </div>
        </div>
        {% else %}
        <div class="header">
            <div class="user-info">
                <div class="user-main">
                    <div class="user-avatar">🏪</div>
                    <div class="user-details">
                        <h1>Торговая площадка</h1>
                        <div style="color: var(--gray);">Обменивайтесь подарками</div>
                    </div>
                </div>
                <div class="user-stats">
                    <div class="balance">⭐ {{ "{:,}".format(user.balance).replace(",", " ") }}</div>
                </div>
            </div>
        </div>

        {% if ad_text %}
        <div class="ad-banner">{{ ad_text }}</div>
        {% endif %}

        <div class="nav">
            <a href="/profile?id={{ user.id }}" class="nav-item">🎁 Мои подарки</a>
            <a href="/shop?id={{ user.id }}" class="nav-item">🛍️ Магазин</a>
            <a href="/market?id={{ user.id }}" class="nav-item active">🏪 Маркет</a>
            <a href="/auction?id={{ user.id }}" class="nav-item">🎯 Аукцион</a>
            {% if user.is_admin %}
            <a href="/admin?id={{ user.id }}" class="nav-item">⚙️ Админ</a>
            {% endif %}
        </div>

        <div class="section-header">
            <h2 class="section-title">Активные предложения</h2>
            <div style="color: var(--gray);">{{ market_items|length }} items</div>
        </div>

        {% if market_items %}
        <div class="grid">
            {% for item in market_items %}
            <div class="card">
                <div class="card-media">
                    {% if item.gift.image %}
                        {% if item.gift.image.endswith('.mp4') or item.gift.image.endswith('.mov') or item.gift.image.endswith('.avi') or item.gift.image.endswith('.webm') %}
                        <video autoplay loop muted playsinline>
                            <source src="{{ item.gift.image }}" type="video/mp4">
                        </video>
                        {% else %}
                        <img src="{{ item.gift.image }}" alt="{{ item.gift.name }}">
                        {% endif %}
                    {% else %}
                    <img src="https://via.placeholder.com/200x200/0F172A/64748B?text=🎁" alt="{{ item.gift.name }}">
                    {% endif %}
                </div>
                
                <div class="card-content">
                    <h3 class="card-title">{{ item.gift.name }}</h3>
                    
                    {% if item.gift.issuer_username %}
                    <div class="issuer-info">
                        Выпущен <a href="https://t.me/{{ item.gift.issuer_username|replace('@', '') }}" class="issuer-link" target="_blank">@{{ item.gift.issuer_username }}</a>
                    </div>
                    {% elif item.gift.issued_by %}
                    <div class="issuer-info">
                        Выпущен @{{ item.gift.issued_by }}
                    </div>
                    {% endif %}
                </div>

                <div class="btn-group">
                    <div class="price">{{ item.price }} ⭐</div>
                    <div class="info">Продавец: {{ item.owner[:8] }}...</div>
                    
                    <button class="btn btn-primary" onclick="buyFromMarket({{ item.market_id }})"
                        {% if item.owner == user.id or user.balance < item.price %}disabled{% endif %}>
                        Купить
                    </button>
                </div>
            </div>
            {% endfor %}
        </div>
        {% else %}
        <div class="empty-state">
            <div class="empty-icon">💸</div>
            <div class="empty-text">На маркете пока пусто</div>
            <div class="empty-subtext">Выставляйте свои подарки на продажу!</div>
        </div>
        {% endif %}
        {% endif %}
    </div>

    <div id="notification" class="notification"></div>
    
    {% if not user.is_banned %}
    <script>
        const userId = "{{ user.id }}";
        
        function showNotification(message, type = 'success') {
            const notification = document.getElementById('notification');
            notification.textContent = message;
            notification.className = 'notification show';
            
            if (type === 'error') {
                notification.style.background = '#EF4444';
            } else {
                notification.style.background = '#10B981';
            }
            
            setTimeout(() => {
                notification.className = 'notification hide';
            }, 3000);
        }

        async function buyFromMarket(marketId) {
            try {
                const response = await fetch(`/market/buy/${marketId}?id=${userId}`, { method: 'POST' });
                const data = await response.json();
                
                if (data.success) {
                    showNotification(data.msg);
                    setTimeout(() => location.reload(), 1000);
                } else {
                    showNotification(data.msg, 'error');
                }
            } catch (error) {
                showNotification('Ошибка при покупке', 'error');
            }
        }
    </script>
    {% endif %}
</body>
</html>'''

AUCTION_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Аукцион • Vortex Market</title>
    ''' + BASE_STYLES + '''
</head>
<body>
    <div class="app-container">
        {% if user.is_banned %}
        <div class="header" style="background: rgba(239, 68, 68, 0.1); border-color: var(--danger);">
            <div style="text-align: center; padding: 20px;">
                <div style="font-size: 48px; margin-bottom: 16px;">🚫</div>
                <h1 style="color: var(--danger); margin-bottom: 8px;">Аккаунт заблокирован</h1>
                <p style="color: var(--gray); margin-bottom: 8px;"><strong>Причина:</strong> {{ user.ban_reason }}</p>
                {% if user.ban_until and user.ban_until != 'permanent' %}
                <p style="color: var(--gray);"><strong>Разблокировка:</strong> {{ user.ban_until }}</p>
                {% else %}
                <p style="color: var(--gray);"><strong>Блокировка:</strong> Бессрочно</p>
                {% endif %}
            </div>
        </div>
        {% else %}
        <div class="header">
            <div class="user-info">
                <div class="user-main">
                    <div class="user-avatar">🎯</div>
                    <div class="user-details">
                        <h1>Аукцион подарков</h1>
                        <div style="color: var(--gray);">Участвуйте и выигрывайте!</div>
                    </div>
                </div>
                <div class="user-stats">
                    <div class="balance">⭐ {{ "{:,}".format(user.balance).replace(",", " ") }}</div>
                </div>
            </div>
        </div>

        {% if ad_text %}
        <div class="ad-banner">{{ ad_text }}</div>
        {% endif %}

        <div class="nav">
            <a href="/profile?id={{ user.id }}" class="nav-item">🎁 Мои подарки</a>
            <a href="/shop?id={{ user.id }}" class="nav-item">🛍️ Магазин</a>
            <a href="/market?id={{ user.id }}" class="nav-item">🏪 Маркет</a>
            <a href="/auction?id={{ user.id }}" class="nav-item active">🎯 Аукцион</a>
            {% if user.is_admin %}
            <a href="/admin?id={{ user.id }}" class="nav-item">⚙️ Админ</a>
            {% endif %}
        </div>

        {% if active_auction %}
        <div class="auction-info">
            <div class="section-header">
                <h2 class="section-title">{{ gift.name }}</h2>
                <div style="color: var(--secondary); font-weight: 700;">Раунд {{ auction.current_round }} из {{ gift.auction_rounds }}</div>
            </div>

            <div class="auction-stats">
                <div class="stat-card">
                    <div class="stat-value">{{ gift.auction_winners_count }}</div>
                    <div class="stat-label">Победителей в раунде</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{{ gift.auction_duration }} мин</div>
                    <div class="stat-label">Длительность раунда</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{{ bids|length }}</div>
                    <div class="stat-label">Всего ставок</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="timeLeft">--:--</div>
                    <div class="stat-label">Осталось времени</div>
                </div>
            </div>

            <div class="auction-media">
                {% if gift.image %}
                    {% if gift.image.endswith('.mp4') or gift.image.endswith('.mov') or gift.image.endswith('.avi') or gift.image.endswith('.webm') %}
                    <video autoplay loop muted playsinline>
                        <source src="{{ gift.image }}" type="video/mp4">
                    </video>
                    {% else %}
                    <img src="{{ gift.image }}" alt="{{ gift.name }}">
                    {% endif %}
                {% else %}
                <img src="https://via.placeholder.com/600x400/0F172A/64748B?text=🎁" alt="{{ gift.name }}">
                {% endif %}
            </div>

            <!-- Форма ставки -->
            <div style="margin-bottom: 24px;">
                <h3 style="margin-bottom: 12px;">Сделать ставку</h3>
                <div style="display: flex; gap: 12px;">
                    <input type="number" id="bidAmount" class="form-input" placeholder="Сумма ставки" min="1" max="{{ user.balance }}">
                    <button class="btn btn-primary" onclick="placeBid()" {% if user.balance <= 0 %}disabled{% endif %}>
                        💰 Сделать ставку
                    </button>
                </div>
                {% if user_bid %}
                <div style="margin-top: 12px; padding: 12px; background: rgba(16, 185, 129, 0.1); border-radius: 8px; border: 1px solid var(--accent);">
                    <strong>Ваша текущая ставка:</strong> {{ user_bid.amount }} ⭐ 
                    <strong>Ваша позиция:</strong> {{ user_position }}/{{ bids|length }}
                </div>
                {% endif %}
            </div>

            <!-- Топ ставок -->
            <div>
                <h3 style="margin-bottom: 12px;">Топ ставок текущего раунда</h3>
                <div class="bids-list">
                    {% for bid in top_bids %}
                    <div class="bid-item">
                        <div class="bid-user">
                            <span class="bid-position">{{ loop.index }}</span>
                            <span>{{ bid.name }}</span>
                            {% if bid.user_id == user.user_id %}
                            <span style="color: var(--secondary);">(Вы)</span>
                            {% endif %}
                        </div>
                        <div class="bid-amount">{{ bid.amount }} ⭐</div>
                    </div>
                    {% endfor %}
                    {% if user_position and user_position > 3 %}
                    <div class="bid-item" style="opacity: 0.7;">
                        <div class="bid-user">
                            <span class="bid-position">{{ user_position }}</span>
                            <span>Ваша позиция</span>
                        </div>
                        <div class="bid-amount">{{ user_bid.amount }} ⭐</div>
                    </div>
                    {% endif %}
                </div>
            </div>
        </div>
        {% else %}
        <div class="empty-state">
            <div class="empty-icon">🎯</div>
            <div class="empty-text">Активных аукционов нет</div>
            <div class="empty-subtext">Следите за обновлениями в канале</div>
        </div>
        {% endif %}
        {% endif %}
    </div>

    <div id="notification" class="notification"></div>

    {% if not user.is_banned and active_auction %}
    <script>
        const userId = "{{ user.id }}";
        const auctionId = {{ auction.auction_id }};
        
        // ФИКС: Правильное преобразование времени окончания
        function parseAuctionEndTime(endTimeStr) {
            // Формат: "день.месяц.год час:минута:секунда"
            const parts = endTimeStr.split(' ');
            const dateParts = parts[0].split('.');
            const timeParts = parts[1].split(':');
            
            // Создаем дату (месяцы в JavaScript начинаются с 0)
            return new Date(
                parseInt(dateParts[2]), // год
                parseInt(dateParts[1]) - 1, // месяц (0-11)
                parseInt(dateParts[0]), // день
                parseInt(timeParts[0]), // час
                parseInt(timeParts[1]), // минута
                parseInt(timeParts[2])  // секунда
            );
        }
        
        const endTime = parseAuctionEndTime("{{ auction.end_time }}");
        
        function showNotification(message, type = 'success') {
            const notification = document.getElementById('notification');
            notification.textContent = message;
            notification.className = 'notification show';
            
            if (type === 'error') {
                notification.style.background = '#EF4444';
            } else {
                notification.style.background = '#10B981';
            }
            
            setTimeout(() => {
                notification.className = 'notification hide';
            }, 3000);
        }

        function updateTimer() {
            const now = new Date();
            const diff = endTime - now;
            
            if (diff <= 0) {
                document.getElementById('timeLeft').textContent = '00:00';
                // Обновляем страницу, если время вышло
                setTimeout(() => {
                    location.reload();
                }, 5000);
                return;
            }
            
            const minutes = Math.floor(diff / 60000);
            const seconds = Math.floor((diff % 60000) / 1000);
            
            document.getElementById('timeLeft').textContent = 
                `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }
        
        // Запускаем таймер
        updateTimer();
        const timerInterval = setInterval(updateTimer, 1000);

        async function placeBid() {
            const amountInput = document.getElementById('bidAmount');
            const amount = parseInt(amountInput.value);
            
            if (isNaN(amount) || amount < 1) {
                showNotification('Введите корректную сумму ставки', 'error');
                return;
            }
            
            if (amount > {{ user.balance }}) {
                showNotification('Недостаточно средств для ставки', 'error');
                return;
            }

            try {
                const response = await fetch(`/auction/bid?id=${userId}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                    body: `amount=${amount}`
                });
                
                const data = await response.json();
                
                if (data.success) {
                    showNotification(data.msg);
                    setTimeout(() => location.reload(), 1000);
                } else {
                    showNotification(data.msg, 'error');
                }
            } catch (error) {
                showNotification('Ошибка при размещении ставки', 'error');
            }
        }

        // Очищаем интервал при уходе со страницы
        window.addEventListener('beforeunload', function() {
            clearInterval(timerInterval);
        });
    </script>
    {% endif %}
</body>
</html>'''

ADMIN_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Админ-панель • Vortex Market</title>
    ''' + BASE_STYLES + '''
</head>
<body>
    <div class="app-container">
        <div class="header">
            <div class="user-info">
                <div class="user-main">
                    <div class="user-avatar">⚙️</div>
                    <div class="user-details">
                        <h1>Панель управления</h1>
                        <div style="color: var(--gray);">Администратор системы</div>
                    </div>
                </div>
            </div>
        </div>

        {% if ad_text %}
        <div class="ad-banner">{{ ad_text }}</div>
        {% endif %}

        <div class="nav">
            <a href="/profile?id={{ user.id }}" class="nav-item">🎁 Мои подарки</a>
            <a href="/shop?id={{ user.id }}" class="nav-item">🛍️ Магазин</a>
            <a href="/market?id={{ user.id }}" class="nav-item">🏪 Маркет</a>
            <a href="/auction?id={{ user.id }}" class="nav-item">🎯 Аукцион</a>
            <a href="/admin?id={{ user.id }}" class="nav-item active">⚙️ Админ</a>
        </div>

        <div class="admin-grid">
            <div class="card">
                <h3 class="card-title">🎁 Новый подарок</h3>
                <form id="addGiftForm" enctype="multipart/form-data">
                    <div class="form-group">
                        <label class="form-label">Название</label>
                        <input type="text" name="name" class="form-input" required>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Количество (-1 = ∞)</label>
                        <input type="number" name="stock" class="form-input" min="-1" value="0" required>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Цена</label>
                        <input type="number" name="price" class="form-input" min="0" value="100" required>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Изображение</label>
                        <input type="file" name="image" class="form-input" accept="*" required>
                    </div>
                    <div style="display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap;">
                        <label style="display: flex; align-items: center; gap: 8px;">
                            <input type="checkbox" name="can_upgrade">
                            <span style="color: var(--light);">Можно улучшить</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 8px;">
                            <input type="checkbox" name="is_nft">
                            <span style="color: var(--light);">С серийным номером</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 8px;">
                            <input type="checkbox" name="for_testers">
                            <span style="color: var(--secondary);">ДЛЯ ТЕСТЕРОВ</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 8px;">
                            <input type="checkbox" name="is_auction" id="isAuctionCheckbox">
                            <span style="color: var(--danger);">АУКЦИОН</span>
                        </label>
                    </div>
                    
                    <!-- Настройки аукциона -->
                    <div id="auctionSettings" style="display: none; margin-bottom: 16px;">
                        <div class="form-group">
                            <label class="form-label">Длительность раунда (минуты)</label>
                            <input type="number" name="auction_duration" class="form-input" min="1" value="10">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Количество победителей в раунде</label>
                            <input type="number" name="auction_winners_count" class="form-input" min="1" value="1">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Количество раундов</label>
                            <input type="number" name="auction_rounds" class="form-input" min="1" value="1">
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <label class="form-label">ID / Username выпустившего (опц.)</label>
                        <input type="text" name="issued_by" class="form-input" placeholder="5002745060 или @admin_username">
                    </div>
                    <button type="submit" class="btn btn-primary">➕ Добавить подарок</button>
                </form>
            </div>

            <div class="card">
                <h3 class="card-title">🎯 Управление аукционами</h3>
                {% if active_auction %}
                <div style="margin-bottom: 20px; padding: 16px; background: rgba(239, 68, 68, 0.1); border-radius: 12px; border: 1px solid var(--danger);">
                    <h4 style="color: var(--danger); margin-bottom: 8px;">Активный аукцион</h4>
                    <p style="margin-bottom: 8px;"><strong>Подарок:</strong> {{ active_auction_gift.name }}</p>
                    <p style="margin-bottom: 8px;"><strong>Раунд:</strong> {{ active_auction.current_round }}/{{ active_auction_gift.auction_rounds }}</p>
                    <p style="margin-bottom: 12px;"><strong>Завершение:</strong> {{ active_auction.end_time }}</p>
                    <button class="btn btn-danger" onclick="deleteAuction({{ active_auction.auction_id }})">
                        🗑️ Удалить аукцион
                    </button>
                </div>
                {% else %}
                <form id="startAuctionForm">
                    <div class="form-group">
                        <label class="form-label">Выберите подарок для аукциона</label>
                        <select name="gift_id" class="form-input" required>
                            {% for gift in gifts %}
                                {% if gift.is_auction and gift.stock > 0 %}
                                <option value="{{ gift.gift_id }}">{{ gift.name }}</option>
                                {% endif %}
                            {% endfor %}
                        </select>
                    </div>
                    <button type="submit" class="btn btn-primary">🚀 Запустить аукцион</button>
                </form>
                {% endif %}
            </div>

            <div class="card">
                <h3 class="card-title">⚡ Новое улучшение</h3>
                <form id="addUpgradeForm" enctype="multipart/form-data">
                    <div class="form-group">
                        <label class="form-label">Базовый подарок</label>
                        <select name="gift_id" class="form-input" required>
                            {% for gift in gifts %}
                                {% if gift.can_upgrade %}
                                <option value="{{ gift.gift_id }}">{{ gift.name }}</option>
                                {% endif %}
                            {% endfor %}
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Название улучшения</label>
                        <input type="text" name="name" class="form-input" required>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Цена улучшения</label>
                        <input type="number" name="price" class="form-input" min="1" required>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Шанс (%)</label>
                        <input type="number" name="chance" class="form-input" min="1" max="100" value="100" required>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Редкость</label>
                        <select name="rarity" class="form-input" required>
                            <option value="common">Обычная (Common)</option>
                            <option value="uncommon">Необычная (Uncommon)</option>
                            <option value="rare">Редкая (Rare)</option>
                            <option value="epic">Эпическая (Epic)</option>
                            <option value="legendary">Легендарная (Legendary)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Изображение улучшения</label>
                        <input type="file" name="image" class="form-input" accept="*" required>
                    </div>
                    <button type="submit" class="btn btn-primary">✨ Добавить улучшение</button>
                </form>
            </div>
            
            <div class="card">
                <h3 class="card-title">🎁 Выдать подарок</h3>
                <form id="giveGiftForm">
                    <div class="form-group">
                        <label class="form-label">ID пользователя</label>
                        <input type="text" name="user_id" class="form-input" required>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Подарок</label>
                        <select name="gift_name" class="form-input" required>
                            {% for gift in gifts %}
                            <option value="{{ gift.name }}">{{ gift.name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Количество</label>
                        <input type="number" name="count" class="form-input" min="1" value="1" required>
                    </div>
                    <button type="submit" class="btn btn-primary">🎁 Выдать подарки</button>
                </form>
            </div>
            
            <div class="card">
                <h3 class="card-title">⭐ Выдать звёзды</h3>
                <form id="addBalanceForm">
                    <div class="form-group">
                        <label class="form-label">ID пользователя</label>
                        <input type="text" name="user_id" class="form-input" required>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Количество звёзд</label>
                        <input type="number" name="amount" class="form-input" min="1" required>
                    </div>
                    <button type="submit" class="btn btn-secondary">💫 Выдать звёзды</button>
                </form>
            </div>

            <div class="card">
                <h3 class="card-title">📢 Рекламный баннер</h3>
                <form id="addAdForm">
                    <div class="form-group">
                        <label class="form-label">Текст рекламы</label>
                        <textarea name="text" class="form-input" rows="3" required></textarea>
                    </div>
                    <button type="submit" class="btn btn-primary">📣 Опубликовать</button>
                </form>
            </div>

            <div class="card">
                <h3 class="card-title">🗑️ Удалить подарок</h3>
                <form id="deleteGiftForm">
                    <div class="form-group">
                        <label class="form-label">Выберите подарок для удаления</label>
                        <select name="gift_id" class="form-input" required>
                            {% for gift in gifts %}
                            <option value="{{ gift.gift_id }}">{{ gift.name }} (ID: {{ gift.gift_id }})</option>
                            {% endfor %}
                        </select>
                    </div>
                    <button type="submit" class="btn btn-danger">🗑️ Удалить подарок</button>
                </form>
            </div>

            <div class="card">
                <h3 class="card-title">👤 Управление пользователями</h3>
                <form id="banUserForm">
                    <div class="form-group">
                        <label class="form-label">Выберите пользователя</label>
                        <select name="user_id" class="form-input" required>
                            {% for user_item in all_users %}
                            <option value="{{ user_item.user_id }}">{{ user_item.name }} (ID: {{ user_item.user_id }})</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Причина бана</label>
                        <input type="text" name="reason" class="form-input" required>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Срок бана</label>
                        <select name="ban_duration" class="form-input" required>
                            <option value="1">1 день</option>
                            <option value="7">7 дней</option>
                            <option value="30">30 дней</option>
                            <option value="permanent">Навсегда</option>
                        </select>
                    </div>
                    <button type="submit" class="btn btn-danger">🚫 Забанить</button>
                </form>
                
                <form id="unbanUserForm" style="margin-top: 20px;">
                    <div class="form-group">
                        <label class="form-label">Разблокировать пользователя</label>
                        <select name="user_id" class="form-input" required>
                            {% for user_item in all_users %}
                            {% if user_item.is_banned %}
                            <option value="{{ user_item.user_id }}">{{ user_item.name }} (ID: {{ user_item.user_id }}) - ЗАБАНЕН</option>
                            {% endif %}
                            {% endfor %}
                        </select>
                    </div>
                    <button type="submit" class="btn btn-secondary">✅ Разбанить</button>
                </form>
            </div>

            <div class="card">
                <h3 class="card-title">🔄 Изменить статус серийного номера</h3>
                <form id="changeNftForm">
                    <div class="form-group">
                        <label class="form-label">Выберите подарок</label>
                        <select name="gift_id" class="form-input" required>
                            {% for gift in gifts %}
                            <option value="{{ gift.gift_id }}">{{ gift.name }} (ID: {{ gift.gift_id }})</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Статус серийного номера</label>
                        <select name="is_nft" class="form-input" required>
                            <option value="1">С серийным номером</option>
                            <option value="0">Без серийного номера</option>
                        </select>
                    </div>
                    <button type="submit" class="btn btn-secondary">🔄 Изменить статус</button>
                </form>
            </div>

            <div class="card">
                <h3 class="card-title">🧪 Изменить статус тестера</h3>
                <form id="changeTesterForm">
                    <div class="form-group">
                        <label class="form-label">Выберите подарок</label>
                        <select name="gift_id" class="form-input" required>
                            {% for gift in gifts %}
                            <option value="{{ gift.gift_id }}">{{ gift.name }} (ID: {{ gift.gift_id }})</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Статус тестера</label>
                        <select name="for_testers" class="form-input" required>
                            <option value="1">Только для тестеров</option>
                            <option value="0">Для всех</option>
                        </select>
                    </div>
                    <button type="submit" class="btn btn-secondary">🧪 Изменить статус</button>
                </form>
            </div>

            <div class="card">
                <h3 class="card-title">📢 Отправить уведомление</h3>
                <form id="sendNotificationForm">
                    <div class="form-group">
                        <label class="form-label">Текст уведомления</label>
                        <textarea name="message" class="form-input" rows="4" required placeholder="Введите текст уведомления..."></textarea>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Тип уведомления</label>
                        <select name="notification_type" class="form-input" required>
                            <option value="new_gifts">🎁 О новых подарках</option>
                            <option value="new_upgrades">⚡ О новых улучшениях</option>
                            <option value="out_of_stock">⚠️ О завершении подарков</option>
                            <option value="auction_start">🎯 О начале аукциона</option>
                        </select>
                    </div>
                    <button type="submit" class="btn btn-primary">📤 Отправить в канал</button>
                </form>
            </div>
        </div>
    </div>

    <div id="notification" class="notification"></div>

    <script>
        const userId = "{{ user.id }}";
        
        function showNotification(message, type = 'success') {
            const notification = document.getElementById('notification');
            notification.textContent = message;
            notification.className = 'notification show';
            
            if (type === 'error') {
                notification.style.background = '#EF4444';
            } else {
                notification.style.background = '#10B981';
            }
            
            setTimeout(() => {
                notification.className = 'notification hide';
            }, 3000);
        }

        // Показать/скрыть настройки аукциона
        document.getElementById('isAuctionCheckbox').addEventListener('change', function() {
            const auctionSettings = document.getElementById('auctionSettings');
            const priceInput = document.querySelector('input[name="price"]');
            const priceLabel = document.querySelector('label[for="price"]');
            
            if (this.checked) {
                auctionSettings.style.display = 'block';
                priceInput.value = '0';
                priceInput.disabled = true;
                priceInput.style.opacity = '0.5';
                priceLabel.style.opacity = '0.5';
            } else {
                auctionSettings.style.display = 'none';
                priceInput.disabled = false;
                priceInput.style.opacity = '1';
                priceLabel.style.opacity = '1';
                if (priceInput.value === '0') {
                    priceInput.value = '100';
                }
            }
        });

        document.getElementById('addGiftForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            formData.set('can_upgrade', this.elements.can_upgrade.checked ? '1' : '0');
            formData.set('is_nft', this.elements.is_nft.checked ? '1' : '0');
            formData.set('for_testers', this.elements.for_testers.checked ? '1' : '0');
            formData.set('is_auction', this.elements.is_auction.checked ? '1' : '0');

            try {
                const response = await fetch(`/admin/add_gift?id=${userId}`, {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                showNotification(data.msg, data.success ? 'success' : 'error');
                if (data.success) {
                    setTimeout(() => location.reload(), 1000);
                }
            } catch (error) {
                showNotification('Ошибка сети при добавлении подарка', 'error');
            }
        });

        document.getElementById('startAuctionForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(this);

            try {
                const response = await fetch(`/admin/start_auction?id=${userId}`, {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                showNotification(data.msg, data.success ? 'success' : 'error');
                if (data.success) {
                    setTimeout(() => location.reload(), 1000);
                }
            } catch (error) {
                showNotification('Ошибка сети при запуске аукциона', 'error');
            }
        });

        async function deleteAuction(auctionId) {
            if (!confirm('Вы уверены, что хотите удалить этот аукцион? Все ставки будут возвращены пользователям.')) {
                return;
            }

            try {
                const response = await fetch(`/admin/delete_auction?id=${userId}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                    body: `auction_id=${auctionId}`
                });
                const data = await response.json();
                showNotification(data.msg, data.success ? 'success' : 'error');
                if (data.success) {
                    setTimeout(() => location.reload(), 1000);
                }
            } catch (error) {
                showNotification('Ошибка сети при удалении аукциона', 'error');
            }
        }

        document.getElementById('addUpgradeForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(this);

            try {
                const response = await fetch(`/admin/add_upgrade?id=${userId}`, {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                showNotification(data.msg, data.success ? 'success' : 'error');
                if (data.success) {
                    setTimeout(() => location.reload(), 1000);
                }
            } catch (error) {
                showNotification('Ошибка сети при добавлении улучшения', 'error');
            }
        });

        document.getElementById('giveGiftForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(this);

            try {
                const response = await fetch(`/admin/give_gift?id=${userId}`, {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                showNotification(data.msg, data.success ? 'success' : 'error');
            } catch (error) {
                showNotification('Ошибка сети при выдаче подарка', 'error');
            }
        });

        document.getElementById('addBalanceForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(this);

            try {
                const response = await fetch(`/admin/add_balance?id=${userId}`, {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                showNotification(data.msg, data.success ? 'success' : 'error');
            } catch (error) {
                showNotification('Ошибка сети при выдаче баланса', 'error');
            }
        });

        document.getElementById('addAdForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(this);

            try {
                const response = await fetch(`/admin/add_ad?id=${userId}`, {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                showNotification(data.msg, data.success ? 'success' : 'error');
            } catch (error) {
                showNotification('Ошибка сети при публикации рекламы', 'error');
            }
        });

        document.getElementById('deleteGiftForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            const giftId = formData.get('gift_id');
            
            if (!confirm(`Вы уверены, что хотите удалить этот подарок? Это действие удалит подарок у всех пользователей и с маркета!`)) {
                return;
            }

            try {
                const response = await fetch(`/admin/delete_gift?id=${userId}`, {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                showNotification(data.msg, data.success ? 'success' : 'error');
                if (data.success) {
                    setTimeout(() => location.reload(), 1000);
                }
            } catch (error) {
                showNotification('Ошибка сети при удалении подарка', 'error');
            }
        });

        document.getElementById('banUserForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            const userIdToBan = formData.get('user_id');
            const reason = formData.get('reason');
            const duration = formData.get('ban_duration');
            
            if (!confirm(`Вы уверены, что хотите забанить пользователя?`)) {
                return;
            }

            try {
                const response = await fetch(`/admin/ban_user?id=${userId}`, {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                showNotification(data.msg, data.success ? 'success' : 'error');
                if (data.success) {
                    setTimeout(() => location.reload(), 1000);
                }
            } catch (error) {
                showNotification('Ошибка сети при бане пользователя', 'error');
            }
        });

        document.getElementById('unbanUserForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            const userIdToUnban = formData.get('user_id');
            
            if (!confirm(`Вы уверены, что хотите разбанить пользователя?`)) {
                return;
            }

            try {
                const response = await fetch(`/admin/unban_user?id=${userId}`, {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                showNotification(data.msg, data.success ? 'success' : 'error');
                if (data.success) {
                    setTimeout(() => location.reload(), 1000);
                }
            } catch (error) {
                showNotification('Ошибка сети при разбане пользователя', 'error');
            }
        });

        document.getElementById('changeNftForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            const giftId = formData.get('gift_id');
            const isNft = formData.get('is_nft');
            
            const action = isNft === '1' ? 'с серийным номером' : 'без серийного номера';
            if (!confirm(`Вы уверены, что хотите сделать этот подарок ${action}?`)) {
                return;
            }

            try {
                const response = await fetch(`/admin/change_nft?id=${userId}`, {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                showNotification(data.msg, data.success ? 'success' : 'error');
                if (data.success) {
                    setTimeout(() => location.reload(), 1000);
                }
            } catch (error) {
                showNotification('Ошибка сети при изменении статуса серийного номера', 'error');
            }
        });

        document.getElementById('changeTesterForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            const giftId = formData.get('gift_id');
            const forTesters = formData.get('for_testers');
            
            const action = forTesters === '1' ? 'сделан доступным только для тестеров' : 'сделан доступным для всех';
            if (!confirm(`Вы уверены, что хотите ${action} для этого подарка?`)) {
                return;
            }

            try {
                const response = await fetch(`/admin/change_tester?id=${userId}`, {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                showNotification(data.msg, data.success ? 'success' : 'error');
                if (data.success) {
                    setTimeout(() => location.reload(), 1000);
                }
            } catch (error) {
                showNotification('Ошибка сети при изменении статуса тестера', 'error');
            }
        });

        document.getElementById('sendNotificationForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            const message = formData.get('message');
            const notificationType = formData.get('notification_type');
            
            if (!confirm(`Отправить уведомление в канал?`)) {
                return;
            }

            try {
                const response = await fetch(`/admin/send_notification?id=${userId}`, {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                showNotification(data.msg, data.success ? 'success' : 'error');
                if (data.success) {
                    this.reset();
                }
            } catch (error) {
                showNotification('Ошибка сети при отправке уведомления', 'error');
            }
        });
    </script>
</body>
</html>'''

# --- ОБРАБОТЧИКИ FLASK ---

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/profile')
def profile():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user:
        return "Пользователь не найден", 404
    user_dict = user_to_dict(user)
    ad = get_active_ad()
    ad_text = ad['text'] if ad else None
    
    return render_template_string(
        PROFILE_HTML, 
        user=user_dict, 
        ad_text=ad_text,
        DOMAIN=DOMAIN, 
        NFT_RECEIVING_ADDRESS=NFT_RECEIVING_ADDRESS,
        NFT_VALUE_IN_STARS=NFT_VALUE_IN_STARS
    )

@app.route('/shop')
def shop():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user:
        return "Пользователь не найден", 404
    
    user_dict = user_to_dict(user)
    all_gifts = [gift_to_dict(g) for g in get_all_gifts()]
    
    gifts_sorted = sorted(all_gifts, key=lambda g: (g['stock'] <= 0 and g['stock'] != -1, g['gift_id']))
    
    ad = get_active_ad()
    ad_text = ad['text'] if ad else None
    
    return render_template_string(SHOP_HTML, user=user_dict, gifts=gifts_sorted, ad_text=ad_text, DOMAIN=DOMAIN)

@app.route('/market')
def market():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user:
        return "Пользователь не найден", 404
    market_items = get_market_list()
    ad = get_active_ad()
    ad_text = ad['text'] if ad else None
    return render_template_string(MARKET_HTML, user=user_to_dict(user), market_items=market_items, ad_text=ad_text, DOMAIN=DOMAIN)

@app.route('/auction')
def auction():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user:
        return "Пользователь не найден", 404
    
    active_auction = get_active_auction()
    user_dict = user_to_dict(user)
    ad = get_active_ad()
    ad_text = ad['text'] if ad else None
    
    if active_auction:
        gift = get_gift_by_id(active_auction['gift_id'])
        gift_dict = gift_to_dict(gift) if gift else None
        
        # Получаем ставки для текущего раунда
        bids = get_auction_bids(active_auction['auction_id'], active_auction['current_round'])
        top_bids = bids[:3]  # Топ 3 ставки
        
        # Находим ставку пользователя
        user_bid = None
        user_position = None
        for i, bid in enumerate(bids):
            if bid['user_id'] == user_dict['user_id']:
                user_bid = bid
                user_position = i + 1
                break
        
        return render_template_string(
            AUCTION_HTML, 
            user=user_dict, 
            active_auction=active_auction,
            auction=active_auction,
            gift=gift_dict,
            bids=bids,
            top_bids=top_bids,
            user_bid=user_bid,
            user_position=user_position,
            ad_text=ad_text,
            DOMAIN=DOMAIN
        )
    else:
        return render_template_string(
            AUCTION_HTML, 
            user=user_dict, 
            active_auction=None,
            auction=None,
            ad_text=ad_text,
            DOMAIN=DOMAIN
        )

@app.route('/admin')
def admin_panel():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user or not user['is_admin']:
        return "Доступ запрещен", 403
    gifts = [gift_to_dict(g) for g in get_all_gifts()]
    all_users = get_all_users()
    ad = get_active_ad()
    ad_text = ad['text'] if ad else None
    active_auction = get_active_auction()
    active_auction_gift = None
    if active_auction:
        active_auction_gift = get_gift_by_id(active_auction['gift_id'])
    return render_template_string(ADMIN_HTML, user=user_to_dict(user), gifts=gifts, all_users=all_users, ad_text=ad_text, active_auction=active_auction, active_auction_gift=active_auction_gift, DOMAIN=DOMAIN)

# --- ОБРАБОТЧИКИ АУКЦИОНОВ ---

@app.route('/auction/bid', methods=['POST'])
def place_bid():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user:
        return jsonify({'success': False, 'msg': 'Пользователь не найден'})

    if user['is_banned']:
        return jsonify({'success': False, 'msg': 'Ваш аккаунт заблокирован'})

    amount = int(request.form.get('amount', 0))
    if amount <= 0:
        return jsonify({'success': False, 'msg': 'Неверная сумма ставки'})

    if user['balance'] < amount:
        return jsonify({'success': False, 'msg': 'Недостаточно средств для ставки'})

    active_auction = get_active_auction()
    if not active_auction:
        return jsonify({'success': False, 'msg': 'Активных аукционов нет'})

    # Проверяем, не закончился ли аукцион
    end_time = datetime.strptime(active_auction['end_time'], "%d.%m.%Y %H:%M:%S")
    if datetime.now() >= end_time:
        return jsonify({'success': False, 'msg': 'Аукцион уже завершен'})

    conn = get_db()
    c = conn.cursor()

    # Проверяем, есть ли уже ставка пользователя в этом раунде
    existing_bid = get_user_bid_in_round(active_auction['auction_id'], user['user_id'], active_auction['current_round'])
    
    if existing_bid:
        # Обновляем существующую ставку
        if existing_bid['amount'] >= amount:
            conn.close()
            return jsonify({'success': False, 'msg': 'Новая ставка должна быть больше текущей'})
        
        # Возвращаем разницу на баланс
        refund_amount = existing_bid['amount']
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (refund_amount, user['user_id']))
        
        # Обновляем ставку
        c.execute("UPDATE auction_bids SET amount = ?, bid_time = ? WHERE bid_id = ?", 
                 (amount, datetime.now().strftime("%d.%m.%Y %H:%M:%S"), existing_bid['bid_id']))
    else:
        # Создаем новую ставку
        c.execute("INSERT INTO auction_bids (auction_id, user_id, round_number, amount, bid_time) VALUES (?, ?, ?, ?, ?)",
                 (active_auction['auction_id'], user['user_id'], active_auction['current_round'], amount, datetime.now().strftime("%d.%m.%Y %H:%M:%S")))

    # Списываем средства
    c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user['user_id']))

    conn.commit()
    conn.close()

    # Отправляем уведомление пользователю
    send_telegram_notification(
        user['user_id'],
        f"💰 *Ставка размещена!*\n\n"
        f"🎁 Аукцион: *{get_gift_by_id(active_auction['gift_id'])['name']}*\n"
        f"🎯 Раунд: *{active_auction['current_round']}*\n"
        f"💫 Сумма: *{amount}* ⭐\n\n"
        f"Следите за своим положением в таблице лидеров!"
    )

    return jsonify({'success': True, 'msg': f'Ставка {amount} ⭐ размещена!'})

# --- НОВЫЕ ОБРАБОТЧИКИ ДЛЯ УДАЛЕНИЯ АУКЦИОНОВ ---

@app.route('/admin/delete_auction', methods=['POST'])
def admin_delete_auction():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'msg': 'Доступ запрещен'})

    auction_id = request.form.get('auction_id')
    if not auction_id:
        return jsonify({'success': False, 'msg': 'Неверные данные'})

    auction = get_auction_by_id(auction_id)
    if not auction:
        return jsonify({'success': False, 'msg': 'Аукцион не найден'})

    conn = get_db()
    c = conn.cursor()

    try:
        # Получаем все ставки для этого аукциона
        bids = get_auction_bids(auction_id)
        
        # Возвращаем средства всем участникам
        for bid in bids:
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bid['amount'], bid['user_id']))
            
            # Уведомляем пользователя о возврате средств
            send_telegram_notification(
                bid['user_id'],
                f"💸 *Средства возвращены!*\n\n"
                f"🎁 Аукцион: *{get_gift_by_id(auction['gift_id'])['name']}*\n"
                f"💰 Возвращено: *{bid['amount']}* ⭐\n"
                f"📊 Причина: Аукцион был удален администратором.\n\n"
                f"Средства возвращены на ваш баланс."
            )
        
        # Удаляем все ставки
        c.execute("DELETE FROM auction_bids WHERE auction_id = ?", (auction_id,))
        
        # Удаляем аукцион
        c.execute("DELETE FROM auctions WHERE auction_id = ?", (auction_id,))
        
        conn.commit()
        conn.close()
        
        # Уведомляем в канал
        send_channel_notification(
            f"🗑️ *Аукцион удален!*\n\n"
            f"🎁 *{get_gift_by_id(auction['gift_id'])['name']}*\n"
            f"✅ Все средства возвращены участникам\n"
            f"📊 Причина: Аукцион удален администратором\n\n"
            f"✨ Следите за новыми аукционами: @VortexMarketBot"
        )
        
        return jsonify({'success': True, 'msg': 'Аукцион удален! Все средства возвращены участникам.'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'msg': f'Ошибка при удалении аукциона: {str(e)}'})

# --- ОБРАБОТЧИКИ ПОПОЛНЕНИЯ БАЛАНСА ---

@app.route('/topup/stars', methods=['POST'])
def topup_stars():
    uid = request.args.get('id')
    amount = int(request.args.get('amount', 0))
    
    user = get_user_by_uid(uid)
    if not user:
        return jsonify({'success': False, 'msg': 'Пользователь не найден'})

    if amount < 1 or amount > 100000:
        return jsonify({'success': False, 'msg': 'Неверная сумма. Допустимо 1-100000 Stars.'})
        
    stars_amount = amount
        
    try:
        invoice_link = bot.create_invoice_link(
            title=f"Пополнение баланса на {stars_amount} ⭐",
            description=f"Пополнение для пользователя {user['name']} ({user['user_id']})",
            payload=f"stars_topup_{user['user_id']}_{stars_amount}_{int(time.time())}",
            provider_token=STARS_TEST_TOKEN,
            currency='XTR',
            prices=[
                types.LabeledPrice(label='Stars', amount=stars_amount)
            ],
            is_flexible=False
        )
        
        send_telegram_notification(
            user['user_id'], 
            f"💰 *Stars-инвойс создан!* Перейдите по [ссылке]({invoice_link}) для оплаты *{stars_amount}* Stars. После оплаты ваш баланс будет пополнен администратором."
        )
        
        return jsonify({
            'success': True, 
            'msg': 'Инвойс успешно создан.',
            'invoice_link': invoice_link
        })
        
    except Exception as e:
        print(f"Ошибка при создании инвойса Stars: {e}")
        return jsonify({'success': False, 'msg': f'Ошибка при создании инвойса Stars. Убедитесь, что токен верен. (Код: {e})'})

@app.route('/topup/nft', methods=['POST'])
def topup_nft():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user:
        return jsonify({'success': False, 'msg': 'Пользователь не найден'})

    conn = get_db()
    c = conn.cursor()

    c.execute("INSERT INTO nft_topups (user_id, request_date, nft_details) VALUES (?, ?, ?)",
             (user['user_id'], datetime.now().strftime("%d.%m.%Y %H:%M:%S"), 'Ожидается подтверждение отправки NFT'))

    conn.commit()
    conn.close()
    
    send_telegram_notification(
        user['user_id'], 
        f"🖼️ *Заявка на NFT-пополнение принята!* Вы уведомили о том, что отправили NFT. "
        f"Администратор проверит это в течение 24 часов и начислит *{NFT_VALUE_IN_STARS}* за каждый NFT ⭐ на ваш баланс."
    )
    
    for admin_id in ADMIN_IDS:
        try:
            send_telegram_notification(
                admin_id,
                f"🆕 *Новая заявка на NFT-пополнение!*\n\n"
                f"👤 Пользователь: *{user['name']}* (ID: `{user['user_id']}`)\n"
                f"💰 Сумма: *{NFT_VALUE_IN_STARS}* ⭐ за каждый NFT\n"
                f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
                f"Проверьте отправку NFT на адрес: `{NFT_RECEIVING_ADDRESS}`"
            )
        except Exception as e:
            print(f"❌ Не удалось отправить уведомление админу {admin_id}: {e}")
    
    return jsonify({
        'success': True, 
        'msg': f'Запрос зарегистрирован! Начисление {NFT_VALUE_IN_STARS} ⭐ в течение 24 часов.'
    })

@app.route('/burn_gift/<int:user_gift_id>', methods=['POST'])
def burn_gift(user_gift_id):
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user:
        return jsonify({'success': False, 'msg': 'Пользователь не найден'})

    if user['is_banned']:
        return jsonify({'success': False, 'msg': 'Ваш аккаунт заблокирован'})

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM user_gifts WHERE id = ? AND user_id = ?", (user_gift_id, user['user_id']))
    user_gift = c.fetchone()
    if not user_gift:
        conn.close()
        return jsonify({'success': False, 'msg': 'Подарок не найден'})

    if user_gift['status'] != 'unupgraded':
        conn.close()
        return jsonify({'success': False, 'msg': 'Можно сжигать только неулучшенные подарки'})

    if user_gift['market_price'] > 0:
        conn.close()
        return jsonify({'success': False, 'msg': 'Нельзя сжигать подарки, выставленные на маркет'})

    c.execute("SELECT * FROM gifts WHERE name = ?", (user_gift['gift_name'],))
    base_gift = c.fetchone()
    if not base_gift:
        conn.close()
        return jsonify({'success': False, 'msg': 'Базовый подарок не найден'})

    refund_amount = int(base_gift['price'] * 0.85)
    
    c.execute("DELETE FROM user_gifts WHERE id = ?", (user_gift_id,))
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (refund_amount, user['user_id']))

    conn.commit()
    conn.close()
    
    send_telegram_notification(
        user['user_id'], 
        f"🔥 *Подарок сожжен!* Вы сожгли \"*{user_gift['gift_name']}*\" и получили *{refund_amount}* ⭐ (85% от стоимости)."
    )

    return jsonify({'success': True, 'msg': f'Подарок сожжен! Вы получили {refund_amount} ⭐ (85% от стоимости)'})

@app.route('/buy/<int:gift_id>', methods=['POST'])
def buy_gift(gift_id):
    uid = request.args.get('id')
    recipient_uid = request.args.get('recipient_uid') 
    
    user = get_user_by_uid(uid)
    if not user:
        return jsonify({'success': False, 'msg': 'Пользователь не найден'})

    if user['is_banned']:
        return jsonify({'success': False, 'msg': 'Ваш аккаунт заблокирован'})

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM gifts WHERE gift_id = ?", (gift_id,))
    gift = c.fetchone()
    if not gift:
        conn.close()
        return jsonify({'success': False, 'msg': 'Подарок не найден'})

    if gift['for_testers'] and not user['is_admin']:
        conn.close()
        return jsonify({'success': False, 'msg': 'Этот подарок доступен только для тестеров'})

    if gift['is_auction']:
        conn.close()
        return jsonify({'success': False, 'msg': 'Этот подарок можно получить только через аукцион'})

    if gift['stock'] != -1 and gift['stock'] <= 0:
        conn.close()
        return jsonify({'success': False, 'msg': 'Подарки закончились'})

    if user['balance'] < gift['price']:
        conn.close()
        return jsonify({'success': False, 'msg': 'Недостаточно средств'})
        
    final_recipient_id = user['user_id']
    target_user = user 
    
    if gift['stock'] == -1:
        if not recipient_uid:
             conn.close()
             return jsonify({'success': False, 'msg': 'Для неограниченных подарков нужно указать ID получателя'})
        
        target_user_row = get_user_by_id(recipient_uid)
        if not target_user_row:
             conn.close()
             return jsonify({'success': False, 'msg': f'Получатель с ID {recipient_uid} не найден'})
             
        if target_user_row['is_banned']:
            conn.close()
            return jsonify({'success': False, 'msg': 'Аккаунт получателя заблокирован'})
             
        target_user = target_user_row
        final_recipient_id = target_user['user_id']
    elif recipient_uid:
        pass

    new_balance = user['balance'] - gift['price']
    c.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user['user_id']))

    if gift['stock'] != -1:
        c.execute("SELECT stock FROM gifts WHERE gift_id = ? AND stock > 0", (gift_id,))
        available_gift = c.fetchone()
        if not available_gift:
            conn.rollback()
            conn.close()
            return jsonify({'success': False, 'msg': 'Подарки закончились'})
            
        c.execute("UPDATE gifts SET stock = stock - 1 WHERE gift_id = ?", (gift_id,))
        
        updated_gift = get_gift_by_id(gift_id)
        if updated_gift and updated_gift['stock'] == 0:
            if updated_gift['out_of_stock_notified'] == 0:
                check_and_notify_out_of_stock(updated_gift['name'], updated_gift['stock'])
                c.execute("UPDATE gifts SET out_of_stock_notified = 1 WHERE gift_id = ?", (gift_id,))
                conn.commit()

    serial_number = None 
    c.execute("INSERT INTO user_gifts (user_id, gift_name, gift_image, date, is_nft, serial_number, issued_by, issuer_username) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
             (final_recipient_id, gift['name'], gift['image'], datetime.now().strftime("%d.%m.%Y %H:%M:%S"), 0, serial_number, gift['issued_by'], gift['issuer_username']))

    conn.commit()
    conn.close()
    
    msg_for_buyer = f"🎉 *Покупка успешна!* Вы купили подарок \"*{gift['name']}*\" за *{gift['price']}* ⭐."
    
    if user['user_id'] != final_recipient_id:
         msg_for_buyer += f" Подарок отправлен пользователю *{target_user['name']}*."
         send_telegram_notification(target_user['user_id'], f"🎁 *Новый подарок!* Пользователь *{user['name']}* отправил вам \"*{gift['name']}*\"!")
         
    send_telegram_notification(user['user_id'], msg_for_buyer)

    return jsonify({'success': True, 'msg': f'Вы купили "{gift["name"]}" за {gift["price"]} ⭐'})

@app.route('/upgrade/<int:user_gift_id>', methods=['POST'])
def upgrade_gift(user_gift_id):
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user:
        return jsonify({'success': False, 'msg': 'Пользователь не найден'})

    if user['is_banned']:
        return jsonify({'success': False, 'msg': 'Ваш аккаунт заблокирован'})

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM user_gifts WHERE id = ? AND user_id = ?", (user_gift_id, user['user_id']))
    user_gift = c.fetchone()
    if not user_gift:
        conn.close()
        return jsonify({'success': False, 'msg': 'Подарок не найден'})

    if user_gift['status'] != 'unupgraded':
        conn.close()
        return jsonify({'success': False, 'msg': 'Этот подарок уже улучшен'})

    c.execute("SELECT * FROM gifts WHERE name = ?", (user_gift['gift_name'],))
    base_gift = c.fetchone()
    if not base_gift or not base_gift['can_upgrade']:
        conn.close()
        return jsonify({'success': False, 'msg': 'Этот подарок нельзя улучшить'})

    upgrades = get_gift_upgrades(base_gift['gift_id'])
    if not upgrades:
        conn.close()
        return jsonify({'success': False, 'msg': 'Для этого подарка нет улучшений'})

    upgrade = get_random_upgrade_by_rarity(upgrades)
    if not upgrade:
        conn.close()
        return jsonify({'success': False, 'msg': 'Ошибка при выборе улучшения'})

    if user['balance'] < upgrade['price']:
        conn.close()
        return jsonify({'success': False, 'msg': f'Недостаточно средств для улучшения. Нужно: {upgrade["price"]}'})

    new_balance = user['balance'] - upgrade['price']
    c.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user['user_id']))

    is_nft_flag = 1
    serial_number_value = get_next_nft_serial_number(user_gift['gift_name'])
    update_message_suffix = f' и получил серийный номер #{serial_number_value}'
    
    c.execute("UPDATE user_gifts SET gift_image = ?, updated = 1, status = 'upgraded', rarity = ?, is_nft = ?, serial_number = ? WHERE id = ?", 
             (upgrade['image'], upgrade['rarity'], is_nft_flag, serial_number_value, user_gift_id))

    conn.commit()
    conn.close()
    
    msg_for_user = f"✨ *Подарок улучшен!* Ваш \"*{user_gift['gift_name']}*\" стал \"*{upgrade['name']}*\" ({upgrade['rarity']}). Он получил серийный номер *#{serial_number_value}*."
    
    send_telegram_notification(user['user_id'], msg_for_user)
    
    return jsonify({'success': True, 'msg': f'Подарок улучшен до {upgrade["name"]}!{update_message_suffix}'})

@app.route('/market/sell/<int:user_gift_id>', methods=['POST'])
def sell_to_market(user_gift_id):
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user:
        return jsonify({'success': False, 'msg': 'Пользователь не найден'})
        
    if user['is_banned']:
        return jsonify({'success': False, 'msg': 'Ваш аккаунт заблокирован'})
        
    price = int(request.args.get('price', 0))
    if price < 125 or price > 250000:
        return jsonify({'success': False, 'msg': 'Неверная цена. Допустимый диапазон: 125-250000'})

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM user_gifts WHERE id = ? AND user_id = ?", (user_gift_id, user['user_id']))
    user_gift = c.fetchone()
    if not user_gift:
        conn.close()
        return jsonify({'success': False, 'msg': 'Подарок не найден'})

    if user_gift['market_price'] > 0:
        conn.close()
        return jsonify({'success': False, 'msg': 'Этот подарок уже на продаже'})
    
    if user_gift['status'] != 'upgraded':
        conn.close()
        return jsonify({'success': False, 'msg': 'Только улучшенные подарки можно продавать'})
    
    if not user_gift['is_nft']:
        conn.close()
        return jsonify({'success': False, 'msg': 'На маркет можно выставлять только подарки с серийным номером'})
    
    c.execute("INSERT INTO market (owner, user_gift_id, price) VALUES (?, ?, ?)", (user['uid'], user_gift_id, price))
    c.execute("UPDATE user_gifts SET status = 'on_market', market_price = ? WHERE id = ?", (price, user_gift_id))

    conn.commit()
    conn.close()

    send_telegram_notification(
        user['user_id'], 
        f"💰 *На продаже!* Ваш \"*{user_gift['gift_name']} #{user_gift['serial_number']}*\" выставлен на маркет за *{price}* ⭐."
    )

    return jsonify({'success': True, 'msg': f'Подарок выставлен на продажу за {price} звёзд!'})

@app.route('/market/change_price/<int:user_gift_id>', methods=['POST'])
def change_market_price(user_gift_id):
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user:
        return jsonify({'success': False, 'msg': 'Пользователь не найден'})
        
    if user['is_banned']:
        return jsonify({'success': False, 'msg': 'Ваш аккаунт заблокирован'})
        
    new_price = int(request.args.get('price', 0))
    if new_price < 125 or new_price > 250000:
        return jsonify({'success': False, 'msg': 'Неверная цена. Допустимый диапазон: 125-250000'})

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM user_gifts WHERE id = ? AND user_id = ?", (user_gift_id, user['user_id']))
    user_gift = c.fetchone()
    if not user_gift:
        conn.close()
        return jsonify({'success': False, 'msg': 'Подарок не найден'})
    
    if user_gift['status'] != 'on_market':
        conn.close()
        return jsonify({'success': False, 'msg': 'Этот подарок не продается'})

    c.execute("UPDATE market SET price = ? WHERE user_gift_id = ?", (new_price, user_gift_id))
    c.execute("UPDATE user_gifts SET market_price = ? WHERE id = ?", (new_price, user_gift_id))

    conn.commit()
    conn.close()

    return jsonify({'success': True, 'msg': f'Цена изменена на {new_price} звёзд!'})

@app.route('/market/remove/<int:user_gift_id>', methods=['POST'])
def remove_from_market(user_gift_id):
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user:
        return jsonify({'success': False, 'msg': 'Пользователь не найден'})

    if user['is_banned']:
        return jsonify({'success': False, 'msg': 'Ваш аккаунт заблокирован'})

    conn = get_db()
    c = conn.cursor()
    
    user_gift = get_user_gift_by_id(user_gift_id)

    c.execute("DELETE FROM market WHERE user_gift_id = ? AND owner = ?", (user_gift_id, user['uid']))
    if c.rowcount == 0:
        conn.close()
        return jsonify({'success': False, 'msg': 'Предложение не найдено'})

    c.execute("UPDATE user_gifts SET status = 'upgraded', market_price = 0 WHERE id = ?", (user_gift_id,))

    conn.commit()
    conn.close()
    
    if user_gift:
        send_telegram_notification(
            user['user_id'], 
            f"❌ *Снято с продажи!* Ваш \"*{user_gift['gift_name']} #{user_gift['serial_number']}*\" снят с маркета."
        )

    return jsonify({'success': True, 'msg': 'Подарок снят с продажи!'})

@app.route('/market/buy/<int:market_id>', methods=['POST'])
def buy_from_market(market_id):
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user:
        return jsonify({'success': False, 'msg': 'Пользователь не найден'})

    if user['is_banned']:
        return jsonify({'success': False, 'msg': 'Ваш аккаунт заблокирован'})

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM market WHERE market_id = ?", (market_id,))
    market_item = c.fetchone()
    if not market_item:
        conn.close()
        return jsonify({'success': False, 'msg': 'Предложение не найдено'})

    if market_item['owner'] == user['uid']:
        conn.close()
        return jsonify({'success': False, 'msg': 'Нельзя купить свой же подарок'})

    c.execute("SELECT * FROM user_gifts WHERE id = ?", (market_item['user_gift_id'],))
    user_gift = c.fetchone()
    if not user_gift:
        conn.close()
        return jsonify({'success': False, 'msg': 'Подарок не найден'})

    owner = get_user_by_uid(market_item['owner'])
    if not owner:
        conn.close()
        return jsonify({'success': False, 'msg': 'Владелец не найден'})

    if user['balance'] < market_item['price']:
        conn.close()
        return jsonify({'success': False, 'msg': 'Недостаточно средств'})

    new_balance_buyer = user['balance'] - market_item['price']
    new_balance_owner = owner['balance'] + market_item['price']
    c.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance_buyer, user['user_id']))
    c.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance_owner, owner['user_id']))

    c.execute("UPDATE user_gifts SET user_id = ?, status = 'upgraded', market_price = 0 WHERE id = ?", (user['user_id'], market_item['user_gift_id']))

    c.execute("DELETE FROM market WHERE market_id = ?", (market_id,))

    conn.commit()
    conn.close()
    
    gift_name = user_gift['gift_name']
    serial_number = user_gift['serial_number']
    price = market_item['price']
    buyer_name = user['name']
    seller_name = owner['name']

    send_telegram_notification(
        user['user_id'], 
        f"✅ *Покупка!* Вы приобрели \"*{gift_name} #{serial_number}*\" у *{seller_name}* за *{price}* ⭐."
    )
    send_telegram_notification(
        owner['user_id'], 
        f"💸 *Продажа!* Ваш \"*{gift_name} #{serial_number}*\" продан пользователю *{buyer_name}* за *{price}* ⭐."
    )

    return jsonify({'success': True, 'msg': f'Вы купили "{user_gift["gift_name"]}" за {market_item["price"]} ⭐!'})

@app.route('/transfer_gift/<int:user_gift_id>', methods=['POST'])
def transfer_gift(user_gift_id):
    uid = request.args.get('id')
    recipient_tg_id = request.args.get('recipient') 
    
    user = get_user_by_uid(uid)
    recipient = get_user_by_id(recipient_tg_id)
    
    if not user:
        return jsonify({'success': False, 'msg': 'Отправитель не найден'})
    if not recipient:
        return jsonify({'success': False, 'msg': f'Получатель с Telegram ID "{recipient_tg_id}" не найден. Убедитесь, что пользователь запустил бота командой /start.'})

    if user['is_banned']:
        return jsonify({'success': False, 'msg': 'Ваш аккаунт заблокирован'})
    if recipient['is_banned']:
        return jsonify({'success': False, 'msg': 'Аккаунт получателя заблокирован'})

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM user_gifts WHERE id = ? AND user_id = ?", (user_gift_id, user['user_id']))
    user_gift = c.fetchone()
    if not user_gift:
        conn.close()
        return jsonify({'success': False, 'msg': 'Подарок не найден'})
        
    if user_gift['status'] == 'on_market':
        conn.close()
        return jsonify({'success': False, 'msg': 'Подарок выставлен на маркет. Сначала снимите его с продажи.'})

    c.execute("UPDATE user_gifts SET user_id = ? WHERE id = ?", (recipient['user_id'], user_gift_id))

    conn.commit()
    conn.close()
    
    gift_name = user_gift['gift_name']
    is_nft = user_gift['is_nft']
    serial_label = f" #{user_gift['serial_number']}" if is_nft else ""
    
    send_telegram_notification(
        user['user_id'], 
        f"➡️ *Подарок передан!* Вы отправили \"*{gift_name}{serial_label}*\" пользователю *{recipient['name']}*."
    )
    send_telegram_notification(
        recipient['user_id'], 
        f"🎁 *Подарок получен!* Пользователь *{user['name']}* отправил вам \"*{gift_name}{serial_label}*\"!"
    )

    return jsonify({'success': True, 'msg': f'Подарок передан пользователю {recipient["name"]}!'})

# --- ОБРАБОТЧИКИ АДМИН-ПАНЕЛИ ---

@app.route('/admin/add_gift', methods=['POST'])
def admin_add_gift():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'msg': 'Доступ запрещен'})

    name = request.form.get('name')
    stock = int(request.form.get('stock', 0))
    price = int(request.form.get('price', 0))
    can_upgrade = 1 if request.form.get('can_upgrade') in ('on', '1') else 0
    is_nft = 1 if request.form.get('is_nft') in ('on', '1') else 0
    for_testers = 1 if request.form.get('for_testers') in ('on', '1') else 0
    is_auction = 1 if request.form.get('is_auction') in ('on', '1') else 0
    
    # Параметры аукциона
    auction_duration = int(request.form.get('auction_duration', 10))
    auction_winners_count = int(request.form.get('auction_winners_count', 1))
    auction_rounds = int(request.form.get('auction_rounds', 1))
    
    issued_by_input = request.form.get('issued_by', '')
    issuer_username = ''
    issued_by = ''
    
    if issued_by_input.startswith('@'):
        issuer_username = issued_by_input.replace('@', '')
    elif issued_by_input.isdigit():
        issued_by = issued_by_input
        
    if not name:
        return jsonify({'success': False, 'msg': 'Название подарка не может быть пустым'})

    # ИСПРАВЛЕНИЕ: Для аукционных подарков цена должна быть 0
    if is_auction:
        price = 0
    elif price <= 0:
        return jsonify({'success': False, 'msg': 'Цена должна быть больше 0 для обычных подарков'})

    if 'image' not in request.files:
        return jsonify({'success': False, 'msg': 'Файл не загружен'})
    file = request.files['image']
    if file.filename == '':
        return jsonify({'success': False, 'msg': 'Файл не выбран'})

    image_path = save_uploaded_file(file)
    if not image_path:
        return jsonify({'success': False, 'msg': 'Неверный формат файла'})

    conn = get_db()
    c = conn.cursor()

    try:
        # Исправленный запрос - добавлены все необходимые поля
        c.execute("""
            INSERT INTO gifts (name, stock, price, image, can_upgrade, is_nft, issued_by, issuer_username, for_testers, is_auction, auction_duration, auction_winners_count, auction_rounds, out_of_stock_notified) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            name, stock, price, image_path, can_upgrade, is_nft, 
            issued_by, issuer_username, for_testers, is_auction, 
            auction_duration, auction_winners_count, auction_rounds
        ))

        conn.commit()
        conn.close()

        # Отправляем уведомление в канал
        try:
            if is_auction:
                gift_type = "🎯 *Новый аукционный подарок!*"
                description = f"🎁 *{name}*\n" \
                             f"⏰ Длительность раунда: *{auction_duration}* мин\n" \
                             f"🏆 Победителей в раунде: *{auction_winners_count}*\n" \
                             f"🎯 Раундов: *{auction_rounds}*\n\n" \
                             f"✨ Следите за началом аукциона: @VortexMarketBot"
            elif for_testers:
                gift_type = "🧪 *Новый подарок для тестеров!*"
                description = f"*{name}*\n" \
                             f"💰 Цена: *{price}* ⭐\n" \
                             f"📦 В наличии: {'∞' if stock == -1 else stock} шт.\n\n" \
                             f"✨ Скорее в магазин: @VortexMarketBot"
            else:
                gift_type = "🎁 *Новый подарок!*"
                description = f"*{name}*\n" \
                             f"💰 Цена: *{price}* ⭐\n" \
                             f"📦 В наличии: {'∞' if stock == -1 else stock} шт.\n\n" \
                             f"✨ Скорее в магазин: @VortexMarketBot"
                     
            message = f"{gift_type}\n\n{description}"
            send_channel_notification(message)
            print(f"✅ Уведомление о новом подарке отправлено в канал: {name}")
        except Exception as e:
            print(f"❌ Ошибка отправки уведомления о новом подарке: {e}")

        return jsonify({'success': True, 'msg': f'Подарок "{name}" добавлен!'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"❌ Ошибка при добавлении подарка в базу: {e}")
        return jsonify({'success': False, 'msg': f'Ошибка при добавлении подарка: {str(e)}'})

@app.route('/admin/start_auction', methods=['POST'])
def admin_start_auction():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'msg': 'Доступ запрещен'})

    gift_id = request.form.get('gift_id')
    if not gift_id:
        return jsonify({'success': False, 'msg': 'Неверные данные'})

    gift = get_gift_by_id(gift_id)
    if not gift:
        return jsonify({'success': False, 'msg': 'Подарок не найден'})

    if not gift['is_auction']:
        return jsonify({'success': False, 'msg': 'Этот подарок не предназначен для аукциона'})

    # Проверяем, нет ли активного аукциона
    active_auction = get_active_auction()
    if active_auction:
        return jsonify({'success': False, 'msg': 'Уже есть активный аукцион'})

    conn = get_db()
    c = conn.cursor()

    start_time = datetime.now()
    end_time = start_time + timedelta(minutes=gift['auction_duration'])

    c.execute("INSERT INTO auctions (gift_id, start_time, end_time, status, current_round, total_rounds) VALUES (?, ?, ?, 'active', 1, ?)",
             (gift_id, start_time.strftime("%d.%m.%Y %H:%M:%S"), end_time.strftime("%d.%m.%Y %H:%M:%S"), gift['auction_rounds']))

    conn.commit()
    conn.close()

    # Отправляем уведомление в канал
    try:
        message = f"🎯 *АУКЦИОН НАЧАЛСЯ!*\n\n" \
                 f"🎁 *{gift['name']}*\n" \
                 f"⏰ Длительность раунда: *{gift['auction_duration']}* мин\n" \
                 f"🏆 Победителей в раунде: *{gift['auction_winners_count']}*\n" \
                 f"🎯 Всего раундов: *{gift['auction_rounds']}*\n" \
                 f"⏳ Завершение 1 раунда: *{end_time.strftime('%d.%m.%Y %H:%M')}*\n\n" \
                 f"✨ Участвуйте: @VortexMarketBot"
                 
        send_channel_notification(message)
        print(f"✅ Уведомление о начале аукциона отправлено в канал: {gift['name']}")
    except Exception as e:
        print(f"❌ Ошибка отправки уведомления о начале аукциона: {e}")

    return jsonify({'success': True, 'msg': f'Аукцион для "{gift["name"]}" запущен!'})

@app.route('/admin/add_upgrade', methods=['POST'])
def admin_add_upgrade():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'msg': 'Доступ запрещен'})

    gift_id = request.form.get('gift_id')
    name = request.form.get('name')
    price = int(request.form.get('price', 0))
    rarity = request.form.get('rarity', 'common')
    chance = int(request.form.get('chance', 100))

    if not gift_id or not name or price <= 0 or chance < 1 or chance > 100:
        return jsonify({'success': False, 'msg': 'Неверные данные'})

    if 'image' not in request.files:
        return jsonify({'success': False, 'msg': 'Файл не загружен'})
    file = request.files['image']
    if file.filename == '':
        return jsonify({'success': False, 'msg': 'Файл не выбран'})

    image_path = save_uploaded_file(file)
    if not image_path:
        return jsonify({'success': False, 'msg': 'Неверный формат файла'})

    conn = get_db()
    c = conn.cursor()

    c.execute("INSERT INTO upgrades (gift_id, name, image, price, rarity, chance) VALUES (?, ?, ?, ?, ?, ?)",
             (gift_id, name, image_path, price, rarity, chance))

    conn.commit()
    conn.close()

    try:
        base_gift = get_gift_by_id(gift_id)
        if base_gift:
            message = f"⚡ *Новое улучшение доступно!*\n\n" \
                     f"*{name}*\n" \
                     f"🎁 Базовый подарок: *{base_gift['name']}*\n" \
                     f"💰 Цена улучшения: *{price}* ⭐\n" \
                     f"🎲 Редкость: *{rarity.upper()}*\n" \
                     f"📊 Шанс: *{chance}%*\n\n" \
                     f"✨ Улучшайте свои подарки: @VortexMarketBot"
                     
            send_channel_notification(message)
            print(f"✅ Уведомление о новом улучшении отправлено в канал: {name}")
    except Exception as e:
        print(f"❌ Ошибка отправки уведомления о новом улучшении: {e}")

    return jsonify({'success': True, 'msg': f'Улучшение "{name}" добавлено!'})

@app.route('/admin/send_notification', methods=['POST'])
def admin_send_notification():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'msg': 'Доступ запрещен'})

    message = request.form.get('message')
    notification_type = request.form.get('notification_type')
    
    if not message:
        return jsonify({'success': False, 'msg': 'Сообщение не может быть пустым'})

    try:
        if notification_type == 'new_gifts':
            formatted_message = f"🎁 *Новые подарки!*\n\n{message}\n\n✨ Скорее в магазин: @VortexMarketBot"
        elif notification_type == 'new_upgrades':
            formatted_message = f"⚡ *Новые улучшения!*\n\n{message}\n\n✨ Улучшайте подарки: @VortexMarketBot"
        elif notification_type == 'out_of_stock':
            formatted_message = f"⚠️ *Подарки закончились!*\n\n{message}\n\n💫 Следите за обновлениями: @VortexMarketBot"
        elif notification_type == 'auction_start':
            formatted_message = f"🎯 *Начинается аукцион!*\n\n{message}\n\n✨ Участвуйте: @VortexMarketBot"
        else:
            formatted_message = f"📢 *Уведомление*\n\n{message}\n\n✨ @VortexMarketBot"
            
        send_channel_notification(formatted_message)
        print(f"✅ Уведомление отправлено в канал: {message[:100]}...")
        return jsonify({'success': True, 'msg': 'Уведомление отправлено в канал!'})
    except Exception as e:
        print(f"❌ Ошибка отправки уведомления: {e}")
        return jsonify({'success': False, 'msg': f'Ошибка отправки: {str(e)}'})

@app.route('/admin/give_gift', methods=['POST'])
def admin_give_gift():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'msg': 'Доступ запрещен'})

    user_id = request.form.get('user_id')
    gift_name = request.form.get('gift_name')
    count = int(request.form.get('count', 1))

    if not user_id or not gift_name or count <= 0:
        return jsonify({'success': False, 'msg': 'Неверные данные'})

    target_user = get_user_by_id(user_id)
    if not target_user:
        return jsonify({'success': False, 'msg': 'Пользователь не найден'})

    gift = get_gift_by_name(gift_name)
    if not gift:
        return jsonify({'success': False, 'msg': 'Подарок не найден'})
        
    if gift['stock'] != -1 and gift['stock'] < count:
        return jsonify({'success': False, 'msg': f'Недостаточно подарков в наличии. В наличии: {gift["stock"]}'})

    conn = get_db()
    c = conn.cursor()
    
    if gift['stock'] != -1:
        c.execute("UPDATE gifts SET stock = stock - ? WHERE name = ?", (count, gift_name))

    for _ in range(count):
        serial_number = None
        c.execute("INSERT INTO user_gifts (user_id, gift_name, gift_image, date, is_nft, serial_number, issued_by, issuer_username) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (user_id, gift['name'], gift['image'], datetime.now().strftime("%d.%m.%Y %H:%M:%S"), 0, serial_number, gift['issued_by'], gift['issuer_username']))

    conn.commit()
    conn.close()

    return jsonify({'success': True, 'msg': f'Выдано {count} шт. "{gift_name}" для пользователя {target_user["name"]}!'})

@app.route('/admin/add_balance', methods=['POST'])
def admin_add_balance():
    uid = request.args.get('id')
    admin = get_user_by_uid(uid)
    if not admin or not admin['is_admin']:
        return jsonify({'success': False, 'msg': 'Доступ запрещен'})

    user_id = request.form.get('user_id')
    amount = int(request.form.get('amount', 0))

    if not user_id or amount <= 0:
        return jsonify({'success': False, 'msg': 'Неверные данные'})

    target_user = get_user_by_id(user_id)
    if not target_user:
        return jsonify({'success': False, 'msg': 'Пользователь не найден'})

    conn = get_db()
    c = conn.cursor()

    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    
    conn.commit()
    conn.close()
    
    send_telegram_notification(
        target_user['user_id'], 
        f"⭐ *Пополнение баланса!* Администратор *{admin['name']}* добавил на ваш счет *{amount}* ⭐."
    )

    return jsonify({'success': True, 'msg': f'Добавлено {amount} ⭐ пользователю {target_user["name"]}!'})

@app.route('/admin/add_ad', methods=['POST'])
def admin_add_ad():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'msg': 'Доступ запрещен'})

    text = request.form.get('text')
    if not text:
        return jsonify({'success': False, 'msg': 'Текст рекламы не может быть пустым'})

    conn = get_db()
    c = conn.cursor()

    c.execute("UPDATE ads SET is_active = 0")
    c.execute("INSERT INTO ads (text, is_active) VALUES (?, 1)", (text,))

    conn.commit()
    conn.close()

    return jsonify({'success': True, 'msg': 'Реклама добавлена!'})

@app.route('/admin/delete_gift', methods=['POST'])
def admin_delete_gift():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'msg': 'Доступ запрещен'})

    gift_id = request.form.get('gift_id')
    if not gift_id:
        return jsonify({'success': False, 'msg': 'Неверные данные'})

    gift = get_gift_by_id(gift_id)
    if not gift:
        return jsonify({'success': False, 'msg': 'Подарок не найден'})

    conn = get_db()
    c = conn.cursor()

    try:
        c.execute("SELECT ug.id FROM user_gifts ug WHERE ug.gift_name = ?", (gift['name'],))
        user_gift_ids = [row['id'] for row in c.fetchall()]
        
        if user_gift_ids:
            placeholders = ','.join('?' * len(user_gift_ids))
            c.execute(f"DELETE FROM market WHERE user_gift_id IN ({placeholders})", user_gift_ids)
        
        c.execute("DELETE FROM user_gifts WHERE gift_name = ?", (gift['name'],))
        
        c.execute("DELETE FROM upgrades WHERE gift_id = ?", (gift_id,))
        
        c.execute("DELETE FROM gifts WHERE gift_id = ?", (gift_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'msg': f'Подарок "{gift["name"]}" и все связанные данные удалены!'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'msg': f'Ошибка при удалении: {str(e)}'})

@app.route('/admin/ban_user', methods=['POST'])
def admin_ban_user():
    uid = request.args.get('id')
    admin = get_user_by_uid(uid)
    if not admin or not admin['is_admin']:
        return jsonify({'success': False, 'msg': 'Доступ запрещен'})

    user_id = request.form.get('user_id')
    reason = request.form.get('reason')
    ban_duration = request.form.get('ban_duration')
    
    if not user_id or not reason:
        return jsonify({'success': False, 'msg': 'Неверные данные'})

    target_user = get_user_by_id(user_id)
    if not target_user:
        return jsonify({'success': False, 'msg': 'Пользователь не найден'})
    
    if target_user['is_admin']:
        return jsonify({'success': False, 'msg': 'Нельзя забанить администратора'})

    conn = get_db()
    c = conn.cursor()

    ban_until = None
    if ban_duration == 'permanent':
        ban_until = 'permanent'
    else:
        days = int(ban_duration)
        ban_date = datetime.now() + timedelta(days=days)
        ban_until = ban_date.strftime("%d.%m.%Y %H:%M:%S")

    c.execute("UPDATE users SET is_banned = 1, ban_reason = ?, ban_until = ? WHERE user_id = ?", 
             (reason, ban_until, user_id))
    
    conn.commit()
    conn.close()
    
    duration_text = "бессрочно" if ban_duration == 'permanent' else f"до {ban_until}"
    send_telegram_notification(
        user_id, 
        f"🚫 *Ваш аккаунт заблокирован!*\n\n"
        f"*Причина:* {reason}\n"
        f"*Блокировка:* {duration_text}\n\n"
        f"Если вы считаете, что это ошибка, свяжитесь с администрацией."
    )

    return jsonify({'success': True, 'msg': f'Пользователь {target_user["name"]} забанен! Причина: {reason}'})

@app.route('/admin/unban_user', methods=['POST'])
def admin_unban_user():
    uid = request.args.get('id')
    admin = get_user_by_uid(uid)
    if not admin or not admin['is_admin']:
        return jsonify({'success': False, 'msg': 'Доступ запрещен'})

    user_id = request.form.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'msg': 'Неверные данные'})

    target_user = get_user_by_id(user_id)
    if not target_user:
        return jsonify({'success': False, 'msg': 'Пользователь не найден'})

    conn = get_db()
    c = conn.cursor()

    c.execute("UPDATE users SET is_banned = 0, ban_reason = NULL, ban_until = NULL WHERE user_id = ?", (user_id,))
    
    conn.commit()
    conn.close()
    
    send_telegram_notification(
        user_id, 
        f"✅ *Ваш аккаунт разблокирован!*\n\n"
        f"Теперь вы снова можете пользоваться всеми функциями бота."
    )

    return jsonify({'success': True, 'msg': f'Пользователь {target_user["name"]} разбанен!'})

@app.route('/admin/change_nft', methods=['POST'])
def admin_change_nft():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'msg': 'Доступ запрещен'})

    gift_id = request.form.get('gift_id')
    is_nft = int(request.form.get('is_nft'))
    
    if not gift_id:
        return jsonify({'success': False, 'msg': 'Неверные данные'})

    gift = get_gift_by_id(gift_id)
    if not gift:
        return jsonify({'success': False, 'msg': 'Подарок не найден'})

    conn = get_db()
    c = conn.cursor()

    c.execute("UPDATE gifts SET is_nft = ? WHERE gift_id = ?", (is_nft, gift_id))
    
    c.execute("UPDATE user_gifts SET is_nft = ? WHERE gift_name = ?", (is_nft, gift['name']))
    
    conn.commit()
    conn.close()

    action = "с серийным номером" if is_nft else "без серийного номера"
    return jsonify({'success': True, 'msg': f'Подарок "{gift["name"]}" теперь {action}!'})

@app.route('/admin/change_tester', methods=['POST'])
def admin_change_tester():
    uid = request.args.get('id')
    user = get_user_by_uid(uid)
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'msg': 'Доступ запрещен'})

    gift_id = request.form.get('gift_id')
    for_testers = int(request.form.get('for_testers'))
    
    if not gift_id:
        return jsonify({'success': False, 'msg': 'Неверные данные'})

    gift = get_gift_by_id(gift_id)
    if not gift:
        return jsonify({'success': False, 'msg': 'Подарок не найден'})

    conn = get_db()
    c = conn.cursor()

    c.execute("UPDATE gifts SET for_testers = ? WHERE gift_id = ?", (for_testers, gift_id))
    
    conn.commit()
    conn.close()

    action = "сделан доступным только для тестеров" if for_testers else "сделан доступным для всех"
    return jsonify({'success': True, 'msg': f'Подарок "{gift["name"]}" {action}!'})

# --- ОБРАБОТЧИКИ TELEGRAM BOT ---

@bot.pre_checkout_query_handler(func=lambda query: True)
def process_pre_checkout_query(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def process_successful_payment(message):
    user_id = str(message.from_user.id)
    payload = message.successful_payment.invoice_payload
    amount = message.successful_payment.total_amount

    if payload.startswith('stars_topup_'):
        conn = get_db()
        c = conn.cursor()
        
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()

        bot.send_message(
            user_id, 
            f"🎉 *Баланс пополнен!* Ваш платеж Stars на сумму *{amount}* ⭐ успешно обработан. Новый баланс доступен в профиле.", 
            parse_mode='Markdown'
        )
    else:
        bot.send_message(
            user_id,
            f"🎉 Успешный платеж на сумму *{amount}* XTR. Спасибо!",
            parse_mode='Markdown'
        )

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = str(message.from_user.id)
    name = message.from_user.first_name if message.from_user.first_name else message.from_user.username
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    
    if not user:
        uid = generate_uid()
        c.execute("INSERT INTO users (user_id, uid, name, balance) VALUES (?, ?, ?, ?)", (user_id, uid, name, START_BALANCE))
        conn.commit()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
    
    conn.close()
    
    if user['is_banned']:
        ban_reason = user['ban_reason'] or 'Не указана'
        ban_until = user['ban_until'] or 'Не указано'
        
        text = f"🚫 *Ваш аккаунт заблокирован!*\n\n" \
               f"*Причина:* {ban_reason}\n" \
               f"*Разблокировка:* {ban_until}\n\n" \
               f"Если вы считаете, что это ошибка, свяжитесь с администрацией."
        
        bot.send_message(message.chat.id, text, parse_mode='Markdown')
        return
    
    ad = get_active_ad()
    ad_text = f"/n📢 *{ad['text']}*" if ad else ""
    
    active_auction = get_active_auction()
    auction_text = ""
    if active_auction:
        gift = get_gift_by_id(active_auction['gift_id'])
        if gift:
            auction_text = f"\n\n🎯 *Активный аукцион!* Участвуйте в аукционе за *{gift['name']}*"
    
    text = f"🤖 *Vortex Market* приветствует Вас!\n\n" \
           f"✨ Пользователь: *{user['name']}*\n" \
           f"Ваш ID: `{user_id}`\n" \
           f"💰 Баланс: *{user['balance']}* ⭐\n\n" \
           f"Перейдите в веб-панель для просмотра и управления коллекцией подарков, а также посещения магазина и маркета.{auction_text}\n\n" \
           f"{ad_text}"
    
    keyboard = types.InlineKeyboardMarkup()
    button = types.InlineKeyboardButton(text="📱 Перейти в профиль", url=f"{DOMAIN}/profile?id={user['uid']}")
    keyboard.add(button)

    bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=keyboard)

@bot.message_handler(func=lambda message: message.text in ['/profile', '/shop', '/market', '/auction'])
def handle_menu_commands(message):
    user_id = str(message.from_user.id)
    user = get_user_by_id(user_id)
    
    if not user:
        bot.send_message(message.chat.id, "❌ Сначала используйте /start")
        return
    
    if user['is_banned']:
        ban_reason = user['ban_reason'] or 'Не указана'
        ban_until = user['ban_until'] or 'Не указано'
        
        text = f"🚫 *Ваш аккаунт заблокирован!*\n\n" \
               f"*Причина:* {ban_reason}\n" \
               f"*Разблокировка:* {ban_until}\n\n" \
               f"Если вы считаете, что это ошибка, свяжитесь с администрацией."
        
        bot.send_message(message.chat.id, text, parse_mode='Markdown')
        return
    
    ad = get_active_ad()
    ad_text = f"📢 {ad['text']}" if ad else ""
    
    active_auction = get_active_auction()
    auction_text = ""
    if active_auction and '/auction' in message.text:
        gift = get_gift_by_id(active_auction['gift_id'])
        if gift:
            auction_text = f"\n\n🎯 Активный аукцион: {gift['name']}"
    
    keyboard = types.InlineKeyboardMarkup()
    
    if '/profile' in message.text:
        button = types.InlineKeyboardButton(text="📱 Профиль", url=f"{DOMAIN}/profile?id={user['uid']}")
        text = "Ваш профиль:"
    elif '/shop' in message.text:
        button = types.InlineKeyboardButton(text="🛍️ Магазин", url=f"{DOMAIN}/shop?id={user['uid']}")
        text = "Магазин подарков:"
    elif '/market' in message.text:
        button = types.InlineKeyboardButton(text="🏪 Маркет", url=f"{DOMAIN}/market?id={user['uid']}")
        text = "Торговая площадка:"
    else:
        button = types.InlineKeyboardButton(text="🎯 Аукцион", url=f"{DOMAIN}/auction?id={user['uid']}")
        text = "Аукцион подарков:"
    
    keyboard.add(button)
    bot.send_message(message.chat.id, f"{text}{auction_text}{ad_text}", reply_markup=keyboard)

@bot.message_handler(commands=['test'])
def test_command(message):
    bot.reply_to(message, "✅ Бот активен! Используйте /start для начала")

# --- ЗАПУСК СЕРВЕРА ---
def run_bot():
    MAX_RETRIES = 5
    DELAY = 5
    
    print("🚀 Запуск Telegram бота...")
    
    for attempt in range(MAX_RETRIES):
        try:
            bot.polling(none_stop=True, interval=0, timeout=30)
            break
        except Exception as e:
            print(f"❌ Ошибка запуска бота (Попытка {attempt + 1}/{MAX_RETRIES}): {e}")
            
            if attempt < MAX_RETRIES - 1:
                print(f"😴 Пауза {DELAY} сек. перед повторной попыткой...")
                time.sleep(DELAY)
            else:
                print("🚨 Превышено максимальное количество попыток. Бот не запущен.")
                
if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    
    print(f"🌐 Запуск Flask-сервера на 0.0.0.0:{PORT}...")
    app.run(host='0.0.0.0', port=PORT, debug=True, use_reloader=False)