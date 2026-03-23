import os
import sqlite3
import shutil
import datetime
import random
from tkinter import *
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import pandas as pd

# ==================== КОНСТАНТЫ ====================
DB_FILE = "shoes.db"
RESOURCES_DIR = "resources"
IMAGES_DIR = "images"
PLACEHOLDER = "picture.png"

BG_MAIN = "#FFFFFF"
BG_SECONDARY = "#7FFF00"
ACCENT = "#00FA9A"
DISCOUNT_BG = "#2E8B57"
OUT_OF_STOCK_BG = "#ADD8E6"

# ==================== РАБОТА С БАЗОЙ ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.executescript('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS manufacturers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            full_name TEXT NOT NULL,
            login TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pickup_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            unit TEXT NOT NULL,
            price REAL NOT NULL,
            supplier_id INTEGER,
            manufacturer_id INTEGER,
            category_id INTEGER,
            discount INTEGER DEFAULT 0,
            stock INTEGER NOT NULL,
            description TEXT,
            image_path TEXT,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id),
            FOREIGN KEY (manufacturer_id) REFERENCES manufacturers(id),
            FOREIGN KEY (category_id) REFERENCES categories(id)
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT UNIQUE NOT NULL,
            order_date TEXT NOT NULL,
            delivery_date TEXT,
            pickup_point_id INTEGER,
            user_id INTEGER,
            pickup_code TEXT,
            status TEXT NOT NULL,
            FOREIGN KEY (pickup_point_id) REFERENCES pickup_points(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_article TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (product_article) REFERENCES products(article)
        );
    ''')
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        import_data(conn)
    conn.close()

def import_data(conn):
    cur = conn.cursor()
    # 1. Категории, производители, поставщики из товаров
    df = pd.read_excel(os.path.join(RESOURCES_DIR, "Tovar.xlsx"))
    categories = df["Категория товара"].dropna().unique()
    manufacturers = df["Производитель"].dropna().unique()
    suppliers = df["Поставщик"].dropna().unique()
    for cat in categories:
        cur.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat,))
    for man in manufacturers:
        cur.execute("INSERT OR IGNORE INTO manufacturers (name) VALUES (?)", (man,))
    for sup in suppliers:
        cur.execute("INSERT OR IGNORE INTO suppliers (name) VALUES (?)", (sup,))
    conn.commit()

    # 2. Пункты выдачи
    df_pp = pd.read_excel(os.path.join(RESOURCES_DIR, "Пункты выдачи_import.xlsx"), header=None)
    for addr in df_pp[0]:
        cur.execute("INSERT OR IGNORE INTO pickup_points (address) VALUES (?)", (addr,))
    conn.commit()

    # 3. Пользователи
    df_users = pd.read_excel(os.path.join(RESOURCES_DIR, "user_import.xlsx"))
    for _, row in df_users.iterrows():
        cur.execute("INSERT INTO users (role, full_name, login, password) VALUES (?,?,?,?)",
                    (row["Роль сотрудника"], row["ФИО"], row["Логин"], row["Пароль"]))
    conn.commit()

    # 4. Товары
    cat_map = {name: id for id, name in cur.execute("SELECT id, name FROM categories")}
    man_map = {name: id for id, name in cur.execute("SELECT id, name FROM manufacturers")}
    sup_map = {name: id for id, name in cur.execute("SELECT id, name FROM suppliers")}

    # Создаём папку images, если её нет
    if not os.path.exists(IMAGES_DIR):
        os.makedirs(IMAGES_DIR)

    for _, row in df.iterrows():
        article = row["Артикул"]
        name = row["Наименование товара"]
        unit = row["Единица измерения"]
        price = float(row["Цена"])
        supplier = row["Поставщик"]
        manufacturer = row["Производитель"]
        category = row["Категория товара"]
        discount = int(row["Действующая скидка"]) if pd.notna(row["Действующая скидка"]) else 0
        stock = int(row["Кол-во на складе"]) if pd.notna(row["Кол-во на складе"]) else 0
        description = row["Описание товара"] if pd.notna(row["Описание товара"]) else ""
        image = row["Фото"] if pd.notna(row["Фото"]) else None
        # Копируем изображение в папку images
        if image and os.path.exists(os.path.join(RESOURCES_DIR, image)):
            src = os.path.join(RESOURCES_DIR, image)
            dest = os.path.join(IMAGES_DIR, image)
            if not os.path.exists(dest):
                shutil.copy(src, dest)
            image_path = os.path.join(IMAGES_DIR, image)  # относительный путь
        else:
            image_path = None
        cur.execute('''
            INSERT INTO products (article, name, unit, price, supplier_id, manufacturer_id, category_id, discount, stock, description, image_path)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ''', (article, name, unit, price, sup_map.get(supplier), man_map.get(manufacturer), cat_map.get(category), discount, stock, description, image_path))
    conn.commit()

    # 5. Заказы
    df_orders = pd.read_excel(os.path.join(RESOURCES_DIR, "Заказ_import.xlsx"))
    user_map = {name: id for id, name in cur.execute("SELECT id, full_name FROM users")}
    pp_map = {addr: id for id, addr in cur.execute("SELECT id, address FROM pickup_points")}
    for _, row in df_orders.iterrows():
        order_num = row["Номер заказа"]
        order_date_raw = row["Дата заказа"]
        if pd.isna(order_date_raw):
            print(f"Пропущена строка заказа {order_num}: нет даты заказа")
            continue
        if isinstance(order_date_raw, str):
            try:
                order_date = datetime.datetime.strptime(order_date_raw, "%d.%m.%Y").date()
            except ValueError:
                print(f"Ошибка в дате заказа {order_date_raw} для заказа {order_num}, строка пропущена")
                continue
        else:
            order_date = pd.to_datetime(order_date_raw).date()
        # Дата доставки
        delivery_raw = row["Дата доставки"]
        if pd.isna(delivery_raw):
            delivery_date = None
        elif isinstance(delivery_raw, str):
            try:
                delivery_date = datetime.datetime.strptime(delivery_raw, "%d.%m.%Y").date()
            except ValueError:
                print(f"Ошибка в дате доставки {delivery_raw} для заказа {order_num}, будет установлена NULL")
                delivery_date = None
        else:
            delivery_date = pd.to_datetime(delivery_raw).date()

        address = row["Адрес пункта выдачи"]
        user_full = row["ФИО авторизированного клиента"]
        pickup_code = row["Код для получения"]
        status = row["Статус заказа"]

        if address in pp_map:
            pp_id = pp_map[address]
        else:
            cur.execute("INSERT INTO pickup_points (address) VALUES (?)", (address,))
            conn.commit()
            pp_id = cur.lastrowid
            pp_map[address] = pp_id

        user_id = user_map.get(user_full)
        if user_id is None:
            print(f"Пропущен заказ {order_num}: пользователь {user_full} не найден")
            continue

        cur.execute('''
            INSERT INTO orders (order_number, order_date, delivery_date, pickup_point_id, user_id, pickup_code, status)
            VALUES (?,?,?,?,?,?,?)
        ''', (order_num, order_date, delivery_date, pp_id, user_id, pickup_code, status))
        order_id = cur.lastrowid

        items_str = row["Артикул заказа"]
        if pd.isna(items_str):
            continue
        items = items_str.split(", ")
        for i in range(0, len(items), 2):
            article = items[i]
            try:
                qty = int(items[i+1])
            except (IndexError, ValueError):
                print(f"Ошибка в разборе артикулов для заказа {order_num}: {items_str}")
                continue
            cur.execute("INSERT INTO order_items (order_id, product_article, quantity) VALUES (?,?,?)",
                        (order_id, article, qty))
    conn.commit()
    print("Данные успешно импортированы.")

# ==================== КЛАССЫ GUI ====================
class App:
    def __init__(self):
        self.root = Tk()
        self.root.title("Обувь - магазин")
        self.root.geometry("1200x600")
        icon_path = os.path.join(RESOURCES_DIR, "icon.ico")
        if os.path.exists(icon_path):
            self.root.iconbitmap(icon_path)
        self.current_user = None
        self.show_login()

    def show_login(self):
        self.clear_window()
        LoginWindow(self.root, self)

    def show_product_list(self):
        self.clear_window()
        ProductListWindow(self.root, self)

    def show_orders(self):
        self.clear_window()
        OrderListWindow(self.root, self)

    def clear_window(self):
        for widget in self.root.winfo_children():
            widget.destroy()

    def run(self):
        self.root.mainloop()

class LoginWindow:
    def __init__(self, parent, app):
        self.app = app
        self.frame = Frame(parent, bg=BG_MAIN)
        self.frame.pack(fill=BOTH, expand=True)
        # логотип
        logo_path = os.path.join(RESOURCES_DIR, "logo.png")
        if os.path.exists(logo_path):
            try:
                img = Image.open(logo_path)
                img = img.resize((200, 100), Image.Resampling.LANCZOS)
                logo = ImageTk.PhotoImage(img)
                Label(self.frame, image=logo, bg=BG_MAIN).pack(pady=10)
                self.frame.logo = logo
            except:
                pass

        Label(self.frame, text="Логин", font=("Times New Roman", 12), bg=BG_MAIN).pack(pady=5)
        self.login_entry = Entry(self.frame, font=("Times New Roman", 12))
        self.login_entry.pack(pady=5)
        Label(self.frame, text="Пароль", font=("Times New Roman", 12), bg=BG_MAIN).pack(pady=5)
        self.password_entry = Entry(self.frame, show="*", font=("Times New Roman", 12))
        self.password_entry.pack(pady=5)
        Button(self.frame, text="Войти", command=self.login, bg=ACCENT, font=("Times New Roman", 12)).pack(pady=5)
        Button(self.frame, text="Войти как гость", command=self.guest_login, bg=BG_SECONDARY, font=("Times New Roman", 12)).pack(pady=5)

    def login(self):
        login = self.login_entry.get()
        password = self.password_entry.get()
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT id, role, full_name FROM users WHERE login=? AND password=?", (login, password))
        user = cur.fetchone()
        conn.close()
        if user:
            self.app.current_user = {"id": user[0], "role": user[1], "full_name": user[2]}
            self.app.show_product_list()
        else:
            messagebox.showerror("Ошибка", "Неверный логин или пароль")

    def guest_login(self):
        self.app.current_user = {"id": None, "role": "guest", "full_name": "Гость"}
        self.app.show_product_list()

class ProductListWindow:
    def __init__(self, parent, app):
        self.app = app
        self.parent = parent
        self.frame = Frame(parent, bg=BG_MAIN)
        self.frame.pack(fill=BOTH, expand=True)

        top_frame = Frame(self.frame, bg=BG_MAIN)
        top_frame.pack(fill=X, padx=10, pady=5)

        # Приветствие и кнопка выхода
        Label(top_frame, text=f"Добро пожаловать, {self.app.current_user['full_name']}", font=("Times New Roman", 12),
              bg=BG_MAIN).pack(side=LEFT)
        Button(top_frame, text="Выйти", command=self.logout, bg=BG_SECONDARY).pack(side=RIGHT)

        self.role = self.app.current_user['role']

        # Для менеджера и администратора создаём два подфрейма: левый (поиск/фильтр) и правый (кнопки)
        if self.role in ('Администратор', 'Менеджер'):
            left_frame = Frame(top_frame, bg=BG_MAIN)
            left_frame.pack(side=LEFT, fill=X, expand=True)
            right_frame = Frame(top_frame, bg=BG_MAIN)
            right_frame.pack(side=RIGHT)

            # Добавляем элементы поиска/фильтра в левый фрейм
            self.add_search_filter_sort(left_frame)

            # Кнопки для администратора
            if self.role == 'Администратор':
                Button(right_frame, text="Удалить товар", command=self.delete_product, bg="#FFA07A").pack(side=RIGHT,
                                                                                                          padx=5)
                Button(right_frame, text="Добавить товар", command=self.add_product, bg=ACCENT).pack(side=RIGHT, padx=5)
            Button(right_frame, text="Заказы", command=self.show_orders, bg=ACCENT).pack(side=RIGHT, padx=5)
        else:
            # Для гостя и клиента – только просмотр, без доп. элементов
            pass

        # Таблица товаров
        self.columns = ("Фото", "Наименование", "Категория", "Описание", "Производитель", "Поставщик", "Цена", "Ед.изм.", "Кол-во", "Скидка")
        self.tree = ttk.Treeview(self.frame, columns=self.columns[1:], show="headings", height=20)
        self.tree.heading("#0", text="Фото")
        self.tree.column("#0", width=80)
        for col in self.columns[1:]:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100)
        self.tree.pack(fill=BOTH, expand=True, padx=10, pady=5)
        scrollbar = ttk.Scrollbar(self.frame, orient=VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.load_products()

        if self.role == 'Администратор':
            self.tree.bind("<Double-1>", self.on_item_double_click)

    def add_search_filter_sort(self, parent):
        # parent – это левый фрейм, куда будем добавлять виджеты поиска/фильтра
        # Поиск
        Label(parent, text="Поиск:", bg=BG_MAIN).pack(side=LEFT)
        self.search_var = StringVar()
        self.search_entry = Entry(parent, textvariable=self.search_var, width=20)
        self.search_entry.pack(side=LEFT, padx=5)
        self.search_var.trace('w', lambda *args: self.load_products())

        # Фильтр по поставщику
        Label(parent, text="Поставщик:", bg=BG_MAIN).pack(side=LEFT, padx=(10,0))
        self.supplier_var = StringVar()
        self.supplier_combo = ttk.Combobox(parent, textvariable=self.supplier_var, state="readonly")
        self.load_suppliers()
        self.supplier_combo.pack(side=LEFT, padx=5)
        self.supplier_var.trace('w', lambda *args: self.load_products())

        # Сортировка
        Label(parent, text="Сортировка по кол-ву:", bg=BG_MAIN).pack(side=LEFT, padx=(10,0))
        self.sort_var = StringVar()
        self.sort_combo = ttk.Combobox(parent, textvariable=self.sort_var, values=("Нет", "По возрастанию", "По убыванию"), state="readonly")
        self.sort_combo.set("Нет")
        self.sort_combo.pack(side=LEFT, padx=5)
        self.sort_var.trace('w', lambda *args: self.load_products())

    def load_suppliers(self):
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT name FROM suppliers ORDER BY name")
        suppliers = [row[0] for row in cur.fetchall()]
        conn.close()
        self.supplier_combo['values'] = ["Все поставщики"] + suppliers
        self.supplier_var.set("Все поставщики")

    def load_products(self):
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        query = '''
            SELECT p.article, p.name, c.name, p.description, m.name, s.name,
                   p.price, p.unit, p.stock, p.discount, p.image_path
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN manufacturers m ON p.manufacturer_id = m.id
            LEFT JOIN suppliers s ON p.supplier_id = s.id
            WHERE 1=1
        '''
        params = []
        # Поиск и фильтрация только для менеджера/админа
        if self.role in ('Менеджер', 'Администратор') and hasattr(self, 'search_var') and self.search_var.get().strip():
            search = self.search_var.get().strip()
            query += " AND (p.name LIKE ? OR p.description LIKE ? OR m.name LIKE ? OR s.name LIKE ?)"
            like = f"%{search}%"
            params.extend([like, like, like, like])
        if self.role in ('Менеджер', 'Администратор') and hasattr(self, 'supplier_var') and self.supplier_var.get() != "Все поставщики":
            query += " AND s.name = ?"
            params.append(self.supplier_var.get())
        # Сортировка только для менеджера/админа
        if self.role in ('Менеджер', 'Администратор') and hasattr(self, 'sort_var') and self.sort_var.get() != "Нет":
            if self.sort_var.get() == "По возрастанию":
                query += " ORDER BY p.stock ASC"
            else:
                query += " ORDER BY p.stock DESC"
        cur.execute(query, params)
        rows = cur.fetchall()
        conn.close()

        for item in self.tree.get_children():
            self.tree.delete(item)

        self.images = {}  # кэш для фото

        for row in rows:
            article, name, category, desc, manuf, supplier, price, unit, stock, discount, img_path = row
            # Формирование цены
            if discount and discount > 0:
                final_price = price * (100 - discount) / 100
                price_text = f"{price:.2f} руб.\n{final_price:.2f} руб."
            else:
                price_text = f"{price:.2f} руб."

            # Загрузка фото
            img_tk = None
            if img_path and os.path.exists(img_path):
                try:
                    pil_img = Image.open(img_path)
                    pil_img.thumbnail((70, 70), Image.Resampling.LANCZOS)
                    img_tk = ImageTk.PhotoImage(pil_img)
                    self.images[article] = img_tk
                except:
                    pass
            else:
                # заглушка
                placeholder = os.path.join(IMAGES_DIR, PLACEHOLDER)
                if os.path.exists(placeholder):
                    try:
                        pil_img = Image.open(placeholder)
                        pil_img.thumbnail((70, 70), Image.Resampling.LANCZOS)
                        img_tk = ImageTk.PhotoImage(pil_img)
                        self.images[article] = img_tk
                    except:
                        pass

            # Вставка
            item_id = self.tree.insert("", END, text="", values=(name, category, desc, manuf, supplier, price_text, unit, stock, f"{discount}%"), tags=(article,))
            if img_tk:
                self.tree.item(item_id, image=img_tk)

            # Цвет фона
            if discount > 15:
                self.tree.item(item_id, tags=("discount", article))
            elif stock == 0:
                self.tree.item(item_id, tags=("out_of_stock", article))
            else:
                self.tree.item(item_id, tags=("normal", article))

        self.tree.tag_configure("discount", background=DISCOUNT_BG)
        self.tree.tag_configure("out_of_stock", background=OUT_OF_STOCK_BG)
        self.tree.tag_configure("normal", background=BG_MAIN)

    def on_item_double_click(self, event):
        item = self.tree.selection()[0]
        article = self.tree.item(item, "tags")[1]
        ProductEditWindow(self.parent, self.app, article, self)

    def add_product(self):
        ProductEditWindow(self.parent, self.app, None, self)

    def delete_product(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Удаление", "Выберите товар для удаления")
            return
        item = selected[0]
        article = self.tree.item(item, "tags")[1]
        # Проверка, есть ли товар в заказах
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM order_items WHERE product_article=?", (article,))
        count = cur.fetchone()[0]
        conn.close()
        if count > 0:
            messagebox.showerror("Ошибка", "Невозможно удалить товар, который присутствует в заказах.")
            return
        if messagebox.askyesno("Подтверждение", f"Удалить товар {article}?"):
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            # Получаем путь к изображению, чтобы удалить файл
            cur.execute("SELECT image_path FROM products WHERE article=?", (article,))
            img_path = cur.fetchone()[0]
            cur.execute("DELETE FROM products WHERE article=?", (article,))
            conn.commit()
            conn.close()
            if img_path and os.path.exists(img_path):
                try:
                    os.remove(img_path)
                except:
                    pass
            self.load_products()
            messagebox.showinfo("Успех", "Товар удалён")

    def logout(self):
        self.app.current_user = None
        self.app.show_login()

    def show_orders(self):
        self.app.show_orders()

class ProductEditWindow:
    def __init__(self, parent, app, article=None, refresh_callback=None):
        self.app = app
        self.refresh_callback = refresh_callback
        self.article = article
        self.image_path = None
        self.window = Toplevel(parent)
        self.window.title("Редактирование товара" if article else "Добавление товара")
        self.window.geometry("500x600")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.grab_set()
        self.load_references()
        self.create_form()
        if article:
            self.load_product_data()
        self.window.protocol("WM_DELETE_WINDOW", self.close)

    def load_references(self):
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        self.categories = {name: id for id, name in cur.execute("SELECT id, name FROM categories")}
        self.manufacturers = {name: id for id, name in cur.execute("SELECT id, name FROM manufacturers")}
        self.suppliers = {name: id for id, name in cur.execute("SELECT id, name FROM suppliers")}
        conn.close()

    def create_form(self):
        frame = Frame(self.window, bg=BG_MAIN)
        frame.pack(padx=10, pady=10, fill=BOTH, expand=True)

        row = 0
        Label(frame, text="Наименование:", bg=BG_MAIN).grid(row=row, column=0, sticky=W, pady=2)
        self.name_entry = Entry(frame, width=40)
        self.name_entry.grid(row=row, column=1, pady=2)
        row += 1

        Label(frame, text="Категория:", bg=BG_MAIN).grid(row=row, column=0, sticky=W, pady=2)
        self.category_var = StringVar()
        self.category_combo = ttk.Combobox(frame, textvariable=self.category_var, values=list(self.categories.keys()), state="readonly")
        self.category_combo.grid(row=row, column=1, pady=2)
        row += 1

        Label(frame, text="Описание:", bg=BG_MAIN).grid(row=row, column=0, sticky=W, pady=2)
        self.desc_text = Text(frame, width=40, height=5)
        self.desc_text.grid(row=row, column=1, pady=2)
        row += 1

        Label(frame, text="Производитель:", bg=BG_MAIN).grid(row=row, column=0, sticky=W, pady=2)
        self.manufacturer_var = StringVar()
        self.manufacturer_combo = ttk.Combobox(frame, textvariable=self.manufacturer_var, values=list(self.manufacturers.keys()), state="readonly")
        self.manufacturer_combo.grid(row=row, column=1, pady=2)
        row += 1

        Label(frame, text="Поставщик:", bg=BG_MAIN).grid(row=row, column=0, sticky=W, pady=2)
        self.supplier_var = StringVar()
        self.supplier_combo = ttk.Combobox(frame, textvariable=self.supplier_var, values=list(self.suppliers.keys()), state="readonly")
        self.supplier_combo.grid(row=row, column=1, pady=2)
        row += 1

        Label(frame, text="Цена:", bg=BG_MAIN).grid(row=row, column=0, sticky=W, pady=2)
        self.price_entry = Entry(frame, width=20)
        self.price_entry.grid(row=row, column=1, pady=2)
        row += 1

        Label(frame, text="Ед.изм.:", bg=BG_MAIN).grid(row=row, column=0, sticky=W, pady=2)
        self.unit_entry = Entry(frame, width=20)
        self.unit_entry.grid(row=row, column=1, pady=2)
        row += 1

        Label(frame, text="Кол-во на складе:", bg=BG_MAIN).grid(row=row, column=0, sticky=W, pady=2)
        self.stock_entry = Entry(frame, width=20)
        self.stock_entry.grid(row=row, column=1, pady=2)
        row += 1

        Label(frame, text="Скидка (%):", bg=BG_MAIN).grid(row=row, column=0, sticky=W, pady=2)
        self.discount_entry = Entry(frame, width=20)
        self.discount_entry.grid(row=row, column=1, pady=2)
        row += 1

        Label(frame, text="Фото:", bg=BG_MAIN).grid(row=row, column=0, sticky=W, pady=2)
        self.photo_btn = Button(frame, text="Выбрать файл", command=self.select_image, bg=BG_SECONDARY)
        self.photo_btn.grid(row=row, column=1, pady=2)
        self.photo_label = Label(frame, text="Файл не выбран", bg=BG_MAIN)
        self.photo_label.grid(row=row+1, column=1, pady=2)
        row += 2

        btn_frame = Frame(frame, bg=BG_MAIN)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=10)
        Button(btn_frame, text="Сохранить", command=self.save_product, bg=ACCENT).pack(side=LEFT, padx=5)
        Button(btn_frame, text="Отмена", command=self.close, bg=BG_SECONDARY).pack(side=LEFT)

    def select_image(self):
        filetypes = (("Image files", "*.jpg *.jpeg *.png *.bmp"), ("All files", "*.*"))
        filename = filedialog.askopenfilename(title="Выберите изображение", filetypes=filetypes)
        if filename:
            try:
                img = Image.open(filename)
                img.thumbnail((300, 200), Image.Resampling.LANCZOS)
                if not os.path.exists(IMAGES_DIR):
                    os.makedirs(IMAGES_DIR)
                ext = os.path.splitext(filename)[1]
                new_name = f"prod_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
                dest_path = os.path.join(IMAGES_DIR, new_name)
                img.save(dest_path)
                self.image_path = dest_path
                self.photo_label.config(text=os.path.basename(dest_path))
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось загрузить изображение: {e}")

    def load_product_data(self):
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute('''
            SELECT name, category_id, description, manufacturer_id, supplier_id, price, unit, stock, discount, image_path
            FROM products WHERE article=?
        ''', (self.article,))
        row = cur.fetchone()
        conn.close()
        if row:
            name, cat_id, desc, man_id, sup_id, price, unit, stock, discount, img_path = row
            self.name_entry.insert(0, name)
            for n, i in self.categories.items():
                if i == cat_id:
                    self.category_var.set(n)
                    break
            self.desc_text.insert(1.0, desc)
            for n, i in self.manufacturers.items():
                if i == man_id:
                    self.manufacturer_var.set(n)
                    break
            for n, i in self.suppliers.items():
                if i == sup_id:
                    self.supplier_var.set(n)
                    break
            self.price_entry.insert(0, str(price))
            self.unit_entry.insert(0, unit)
            self.stock_entry.insert(0, str(stock))
            self.discount_entry.insert(0, str(discount))
            if img_path and os.path.exists(img_path):
                self.image_path = img_path
                self.photo_label.config(text=os.path.basename(img_path))
            else:
                self.image_path = None

    def save_product(self):
        try:
            price = float(self.price_entry.get())
            if price < 0:
                raise ValueError("Цена не может быть отрицательной")
        except:
            messagebox.showerror("Ошибка", "Цена должна быть числом >=0")
            return
        try:
            stock = int(self.stock_entry.get())
            if stock < 0:
                raise ValueError("Количество не может быть отрицательным")
        except:
            messagebox.showerror("Ошибка", "Количество должно быть целым неотрицательным числом")
            return
        discount = int(self.discount_entry.get()) if self.discount_entry.get() else 0
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showerror("Ошибка", "Наименование обязательно")
            return
        cat_name = self.category_var.get()
        man_name = self.manufacturer_var.get()
        sup_name = self.supplier_var.get()
        if not cat_name or not man_name or not sup_name:
            messagebox.showerror("Ошибка", "Выберите категорию, производителя и поставщика")
            return
        cat_id = self.categories[cat_name]
        man_id = self.manufacturers[man_name]
        sup_id = self.suppliers[sup_name]
        unit = self.unit_entry.get().strip()
        description = self.desc_text.get("1.0", END).strip()

        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        if self.article:
            cur.execute("SELECT image_path FROM products WHERE article=?", (self.article,))
            old_img = cur.fetchone()[0]
            if self.image_path and old_img and old_img != self.image_path and os.path.exists(old_img):
                os.remove(old_img)
            cur.execute('''
                UPDATE products SET name=?, category_id=?, description=?, manufacturer_id=?, supplier_id=?,
                price=?, unit=?, stock=?, discount=?, image_path=?
                WHERE article=?
            ''', (name, cat_id, description, man_id, sup_id, price, unit, stock, discount, self.image_path, self.article))
        else:
            cur.execute("SELECT MAX(id) FROM products")
            max_id = cur.fetchone()[0] or 0
            article = f"P{max_id+1}"
            cur.execute('''
                INSERT INTO products (article, name, category_id, description, manufacturer_id, supplier_id, price, unit, stock, discount, image_path)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ''', (article, name, cat_id, description, man_id, sup_id, price, unit, stock, discount, self.image_path))
        conn.commit()
        conn.close()
        if self.refresh_callback:
            self.refresh_callback.load_products()
        self.close()

    def close(self):
        self.window.destroy()

class OrderListWindow:
    def __init__(self, parent, app):
        self.app = app
        self.parent = parent
        self.frame = Frame(parent, bg=BG_MAIN)
        self.frame.pack(fill=BOTH, expand=True)

        top_frame = Frame(self.frame, bg=BG_MAIN)
        top_frame.pack(fill=X, padx=10, pady=5)
        Label(top_frame, text=f"Заказы - {self.app.current_user['full_name']}", font=("Times New Roman", 12), bg=BG_MAIN).pack(side=LEFT)
        Button(top_frame, text="Назад", command=self.back, bg=BG_SECONDARY).pack(side=RIGHT)

        if self.app.current_user['role'] == 'Администратор':
            Button(top_frame, text="Добавить заказ", command=self.add_order, bg=ACCENT).pack(side=RIGHT, padx=5)
            Button(top_frame, text="Удалить заказ", command=self.delete_order, bg="#FFA07A").pack(side=RIGHT, padx=5)

        columns = ("Номер", "Дата заказа", "Дата доставки", "Адрес выдачи", "Клиент", "Статус")
        self.tree = ttk.Treeview(self.frame, columns=columns, show="headings", height=20)
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=150)
        self.tree.pack(fill=BOTH, expand=True, padx=10, pady=5)
        scrollbar = ttk.Scrollbar(self.frame, orient=VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.load_orders()
        if self.app.current_user['role'] == 'Администратор':
            self.tree.bind("<Double-1>", self.on_item_double_click)

    def load_orders(self):
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute('''
            SELECT o.id, o.order_number, o.order_date, o.delivery_date, p.address, u.full_name, o.status
            FROM orders o
            LEFT JOIN pickup_points p ON o.pickup_point_id = p.id
            LEFT JOIN users u ON o.user_id = u.id
            ORDER BY o.order_date DESC
        ''')
        rows = cur.fetchall()
        conn.close()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in rows:
            order_id, number, order_date, delivery_date, address, client, status = row
            self.tree.insert("", END, values=(number, order_date, delivery_date, address, client, status), tags=(order_id,))

    def on_item_double_click(self, event):
        item = self.tree.selection()[0]
        order_id = self.tree.item(item, "tags")[0]
        OrderEditWindow(self.parent, self.app, order_id, self)

    def add_order(self):
        OrderEditWindow(self.parent, self.app, None, self)

    def delete_order(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Удаление", "Выберите заказ для удаления")
            return
        item = selected[0]
        order_id = self.tree.item(item, "tags")[0]
        if messagebox.askyesno("Подтверждение", "Удалить заказ?"):
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            # При удалении заказа удалятся и связанные строки из order_items (ON DELETE CASCADE)
            cur.execute("DELETE FROM orders WHERE id=?", (order_id,))
            conn.commit()
            conn.close()
            self.load_orders()
            messagebox.showinfo("Успех", "Заказ удалён")

    def back(self):
        self.app.show_product_list()

class OrderEditWindow:
    def __init__(self, parent, app):
        self.app = app
        self.parent = parent
        self.frame = Frame(parent, bg=BG_MAIN)
        self.frame.pack(fill=BOTH, expand=True)

        # Верхняя панель
        top_frame = Frame(self.frame, bg=BG_MAIN)
        top_frame.pack(fill=X, padx=10, pady=5)

        # Левая часть: приветствие и элементы управления (поиск, фильтр, сортировка)
        left_frame = Frame(top_frame, bg=BG_MAIN)
        left_frame.pack(side=LEFT, fill=X, expand=True)

        Label(left_frame, text=f"Добро пожаловать, {self.app.current_user['full_name']}", font=("Times New Roman", 12),
              bg=BG_MAIN).pack(side=LEFT)

        self.role = self.app.current_user['role']
        if self.role in ('Менеджер', 'Администратор'):
            self.add_search_filter_sort(left_frame)

        # Правая часть: кнопки
        right_frame = Frame(top_frame, bg=BG_MAIN)
        right_frame.pack(side=RIGHT)

        Button(right_frame, text="Выйти", command=self.logout, bg=BG_SECONDARY).pack(side=RIGHT, padx=2)

        if self.role in ('Менеджер', 'Администратор'):
            Button(right_frame, text="Заказы", command=self.show_orders, bg=ACCENT).pack(side=RIGHT, padx=2)
            if self.role == 'Администратор':
                Button(right_frame, text="Удалить товар", command=self.delete_product, bg="#FFA07A").pack(side=RIGHT,
                                                                                                          padx=2)
                Button(right_frame, text="Добавить товар", command=self.add_product, bg=ACCENT).pack(side=RIGHT, padx=2)

        # Таблица товаров
        self.columns = (
        "Фото", "Наименование", "Категория", "Описание", "Производитель", "Поставщик", "Цена", "Ед.изм.", "Кол-во",
        "Скидка")
        self.tree = ttk.Treeview(self.frame, columns=self.columns[1:], show="headings", height=20)
        self.tree.heading("#0", text="Фото")
        self.tree.column("#0", width=80)
        for col in self.columns[1:]:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100)
        self.tree.pack(fill=BOTH, expand=True, padx=10, pady=5)
        scrollbar = ttk.Scrollbar(self.frame, orient=VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.load_products()
        if self.role == 'Администратор':
            self.tree.bind("<Double-1>", self.on_item_double_click)

    def load_references(self):
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        self.pickup_points = {addr: id for id, addr in cur.execute("SELECT id, address FROM pickup_points")}
        self.users = {full: id for id, full in cur.execute("SELECT id, full_name FROM users WHERE role='client'")}
        conn.close()

    def create_form(self):
        frame = Frame(self.window, bg=BG_MAIN)
        frame.pack(padx=10, pady=10, fill=BOTH, expand=True)
        row = 0
        Label(frame, text="Номер заказа:", bg=BG_MAIN).grid(row=row, column=0, sticky=W, pady=2)
        self.number_entry = Entry(frame, state='readonly' if self.order_id else 'normal', width=30)
        self.number_entry.grid(row=row, column=1, pady=2)
        row += 1

        Label(frame, text="Статус:", bg=BG_MAIN).grid(row=row, column=0, sticky=W, pady=2)
        self.status_var = StringVar()
        self.status_combo = ttk.Combobox(frame, textvariable=self.status_var, values=("Новый", "Завершен"), state="readonly")
        self.status_combo.grid(row=row, column=1, pady=2)
        row += 1

        Label(frame, text="Адрес выдачи:", bg=BG_MAIN).grid(row=row, column=0, sticky=W, pady=2)
        self.address_var = StringVar()
        self.address_combo = ttk.Combobox(frame, textvariable=self.address_var, values=list(self.pickup_points.keys()), state="readonly")
        self.address_combo.grid(row=row, column=1, pady=2)
        row += 1

        Label(frame, text="Дата заказа:", bg=BG_MAIN).grid(row=row, column=0, sticky=W, pady=2)
        self.order_date_entry = Entry(frame, width=30)
        self.order_date_entry.grid(row=row, column=1, pady=2)
        row += 1

        Label(frame, text="Дата выдачи:", bg=BG_MAIN).grid(row=row, column=0, sticky=W, pady=2)
        self.delivery_date_entry = Entry(frame, width=30)
        self.delivery_date_entry.grid(row=row, column=1, pady=2)
        row += 1

        if not self.order_id:
            Label(frame, text="Клиент:", bg=BG_MAIN).grid(row=row, column=0, sticky=W, pady=2)
            self.client_var = StringVar()
            self.client_combo = ttk.Combobox(frame, textvariable=self.client_var, values=list(self.users.keys()), state="readonly")
            self.client_combo.grid(row=row, column=1, pady=2)
            row += 1

        btn_frame = Frame(frame, bg=BG_MAIN)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=10)
        Button(btn_frame, text="Сохранить", command=self.save_order, bg=ACCENT).pack(side=LEFT, padx=5)
        Button(btn_frame, text="Отмена", command=self.close, bg=BG_SECONDARY).pack(side=LEFT)

    def load_order_data(self):
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute('''
            SELECT order_number, status, pickup_point_id, order_date, delivery_date
            FROM orders WHERE id=?
        ''', (self.order_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            num, status, pp_id, order_date, delivery_date = row
            self.number_entry.config(state='normal')
            self.number_entry.delete(0, END)
            self.number_entry.insert(0, num)
            self.number_entry.config(state='readonly')
            self.status_var.set(status)
            for addr, i in self.pickup_points.items():
                if i == pp_id:
                    self.address_var.set(addr)
                    break
            self.order_date_entry.insert(0, order_date)
            if delivery_date:
                self.delivery_date_entry.insert(0, delivery_date)

    def save_order(self):
        order_date = self.order_date_entry.get().strip()
        delivery_date = self.delivery_date_entry.get().strip() or None
        try:
            datetime.datetime.strptime(order_date, "%Y-%m-%d")
            if delivery_date:
                datetime.datetime.strptime(delivery_date, "%Y-%m-%d")
        except:
            messagebox.showerror("Ошибка", "Даты должны быть в формате YYYY-MM-DD")
            return
        status = self.status_var.get()
        address = self.address_var.get()
        if not address:
            messagebox.showerror("Ошибка", "Выберите адрес выдачи")
            return
        pp_id = self.pickup_points[address]
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        if self.order_id:
            cur.execute('''
                UPDATE orders SET status=?, pickup_point_id=?, order_date=?, delivery_date=?
                WHERE id=?
            ''', (status, pp_id, order_date, delivery_date, self.order_id))
        else:
            cur.execute("SELECT MAX(id) FROM orders")
            max_id = cur.fetchone()[0] or 0
            new_num = f"Z{max_id+1}"
            user_id = self.users[self.client_var.get()]
            pickup_code = str(random.randint(100, 999))
            cur.execute('''
                INSERT INTO orders (order_number, status, pickup_point_id, order_date, delivery_date, user_id, pickup_code)
                VALUES (?,?,?,?,?,?,?)
            ''', (new_num, status, pp_id, order_date, delivery_date, user_id, pickup_code))
        conn.commit()
        conn.close()
        if self.refresh_callback:
            self.refresh_callback.load_orders()
        self.close()

    def close(self):
        self.window.destroy()

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    if not os.path.exists(IMAGES_DIR):
        os.makedirs(IMAGES_DIR)
    placeholder_src = os.path.join(RESOURCES_DIR, PLACEHOLDER)
    placeholder_dst = os.path.join(IMAGES_DIR, PLACEHOLDER)
    if os.path.exists(placeholder_src) and not os.path.exists(placeholder_dst):
        shutil.copy(placeholder_src, placeholder_dst)
    init_db()
    app = App()
    app.run()