"""Генерация диаграмм для бизнес-планов beauty и barber."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).parent / "charts"
OUT.mkdir(exist_ok=True)

NAVY = "#1e3a5f"
ACCENT = "#c9a961"
GREEN = "#4a7c59"
RED = "#a84444"
GREY = "#6c757d"
LIGHT = "#e8eef5"


def save(fig, name: str) -> None:
    fig.tight_layout()
    fig.savefig(OUT / name, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ============ BEAUTY ============

# 1. Рост beauty-рынка UZ (3 года)
def beauty_market_growth() -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    years = ["2022", "2023", "2024", "2025*", "2026*"]
    revenue_bln = [2.8, 3.57, 4.58, 5.86, 7.5]
    bars = ax.bar(years, revenue_bln, color=[GREY, GREY, NAVY, ACCENT, ACCENT], edgecolor="white", linewidth=2)
    ax.set_ylabel("Оборот, трлн сум", fontsize=11)
    ax.set_title("Рынок салонов красоты и парикмахерских Узбекистана\n(данные stat.uz, прогноз +28% г/г)", fontsize=12, fontweight="bold")
    for bar, val in zip(bars, revenue_bln):
        ax.text(bar.get_x() + bar.get_width()/2, val + 0.15, f"{val} трлн", ha="center", fontsize=10, fontweight="bold")
    ax.set_ylim(0, 9)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    save(fig, "beauty_market_growth.png")


# 2. Сравнение цен конкурентов
def competitors_price() -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    names = ["Твой\n«Solo»", "Твой\n«Studio»", "DIKIDI\n(free+paid)", "YClients\n3 сотр.", "YClients\n10 сотр.", "Твой\n«Pro»"]
    prices = [50, 150, 80, 190, 420, 400]
    colors = [GREEN, GREEN, GREY, RED, RED, GREEN]
    bars = ax.bar(names, prices, color=colors, edgecolor="white", linewidth=2)
    ax.set_ylabel("Цена, тыс сум/мес", fontsize=11)
    ax.set_title("Сравнение тарифов с конкурентами (в сумах)", fontsize=12, fontweight="bold")
    for bar, val in zip(bars, prices):
        ax.text(bar.get_x() + bar.get_width()/2, val + 10, f"{val}к", ha="center", fontsize=10, fontweight="bold")
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    save(fig, "competitors_price.png")


# 3. TAM/SAM/SOM воронка
def tam_sam_som(title: str, tam: int, sam: int, som: int, fname: str) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    levels = ["TAM\n(весь рынок UZ)", "SAM\n(достижимый)", "SOM\n(реально захватить)"]
    values = [tam, sam, som]
    colors = [LIGHT, ACCENT, NAVY]
    bars = ax.barh(levels, values, color=colors, edgecolor="white", linewidth=2)
    ax.set_xlabel("Количество точек", fontsize=11)
    ax.set_title(title, fontsize=12, fontweight="bold")
    for bar, val in zip(bars, values):
        ax.text(val + max(values)*0.01, bar.get_y() + bar.get_height()/2, f"{val:,}".replace(",", " "), va="center", fontsize=11, fontweight="bold")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3)
    ax.set_axisbelow(True)
    save(fig, fname)


# 4. Прогноз MRR 18 мес (3 сценария)
def mrr_forecast(title: str, conservative_end: int, realistic_end: int, optimistic_end: int, fname: str) -> None:
    fig, ax = plt.subplots(figsize=(10, 5.5))
    months = np.arange(0, 19)
    # S-кривая адопции
    def scurve(end: float, steepness: float = 0.35, midpoint: float = 10) -> np.ndarray:
        return end / (1 + np.exp(-steepness * (months - midpoint)))
    conservative = scurve(conservative_end)
    realistic = scurve(realistic_end)
    optimistic = scurve(optimistic_end)
    ax.plot(months, conservative, color=GREY, linewidth=2.5, label=f"Консервативно (→ {conservative_end} млн сум)", marker="o", markersize=4)
    ax.plot(months, realistic, color=NAVY, linewidth=2.8, label=f"Реалистично (→ {realistic_end} млн сум)", marker="s", markersize=5)
    ax.plot(months, optimistic, color=ACCENT, linewidth=2.5, label=f"Оптимистично (→ {optimistic_end} млн сум)", marker="^", markersize=4)
    ax.fill_between(months, 0, conservative, alpha=0.08, color=GREY)
    ax.fill_between(months, conservative, realistic, alpha=0.12, color=NAVY)
    ax.fill_between(months, realistic, optimistic, alpha=0.10, color=ACCENT)
    ax.set_xlabel("Месяц от запуска", fontsize=11)
    ax.set_ylabel("MRR, млн сум/мес", fontsize=11)
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.legend(loc="upper left", fontsize=10, framealpha=0.95)
    ax.grid(True, alpha=0.3)
    ax.set_xticks(months)
    save(fig, fname)


# 5. Break-even: расходы vs доходы
def break_even(title: str, monthly_fixed: int, arpu_k_sum: int, fname: str) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    months = np.arange(0, 19)
    # Клиентов растёт по S-кривой
    clients = 200 / (1 + np.exp(-0.35 * (months - 10)))
    revenue = clients * arpu_k_sum / 1000  # в млн сум
    costs = np.full_like(months, monthly_fixed, dtype=float)
    ax.fill_between(months, 0, revenue, alpha=0.25, color=GREEN, label="Выручка")
    ax.plot(months, revenue, color=GREEN, linewidth=2.5)
    ax.plot(months, costs, color=RED, linewidth=2, linestyle="--", label=f"Постоянные расходы ({monthly_fixed} млн сум)")
    idx = np.where(revenue >= costs)[0]
    if len(idx) > 0:
        be_month = idx[0]
        ax.axvline(be_month, color=NAVY, linestyle=":", alpha=0.7)
        ax.annotate(f"Break-even\nмесяц {be_month}", xy=(be_month, costs[0]), xytext=(be_month + 1, costs[0] + 2),
                    fontsize=10, fontweight="bold", color=NAVY,
                    arrowprops=dict(arrowstyle="->", color=NAVY))
    ax.set_xlabel("Месяц от запуска", fontsize=11)
    ax.set_ylabel("млн сум/мес", fontsize=11)
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.legend(loc="upper left", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_xticks(months)
    save(fig, fname)


# 6. Roadmap
def roadmap(fname: str) -> None:
    fig, ax = plt.subplots(figsize=(11, 4.5))
    phases = [
        ("Этап 1: MVP+uz-локализация", 0, 1, "#b8d4e3"),
        ("Этап 2: Multi-tenancy + веб-админка", 1, 2, "#8cb4cf"),
        ("Этап 3: Пилот 5 клиентов бесплатно", 3, 1, "#c9a961"),
        ("Этап 4: Платные продажи, маркетинг", 4, 4, "#4a7c59"),
        ("Этап 5: Масштабирование (KZ, KG)", 8, 10, "#1e3a5f"),
    ]
    for i, (name, start, dur, color) in enumerate(phases):
        ax.barh(i, dur, left=start, color=color, edgecolor="white", linewidth=2)
        ax.text(start + dur/2, i, name, ha="center", va="center", fontsize=10, color="white" if i >= 3 else "black", fontweight="bold")
    ax.set_yticks([])
    ax.set_xlabel("Месяцы от старта", fontsize=11)
    ax.set_title("Roadmap: 18 месяцев от кода до SaaS-бизнеса", fontsize=12, fontweight="bold")
    ax.set_xticks(range(0, 19))
    ax.set_xlim(0, 18)
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3)
    ax.set_axisbelow(True)
    save(fig, fname)


# 7. Messengers UZ
def messengers_uz() -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    apps = ["Telegram", "Instagram DM", "WhatsApp", "Messenger", "Viber"]
    pct = [88, 62, 18, 6, 4]
    colors = [NAVY, ACCENT, GREY, GREY, GREY]
    bars = ax.barh(apps, pct, color=colors, edgecolor="white", linewidth=2)
    ax.set_xlabel("% аудитории UZ", fontsize=11)
    ax.set_title("Проникновение мессенджеров в Узбекистане\nTelegram — национальная инфраструктура", fontsize=12, fontweight="bold")
    for bar, val in zip(bars, pct):
        ax.text(val + 1, bar.get_y() + bar.get_height()/2, f"{val}%", va="center", fontsize=11, fontweight="bold")
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.grid(axis="x", alpha=0.3)
    ax.set_axisbelow(True)
    save(fig, "messengers_uz.png")


# 8. Barbershops by region
def barbers_by_region() -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    regions = ["Фергана", "Самарканд", "Ташкент", "Андижан", "Бухара", "Наманган", "Прочие"]
    counts = [102, 100, 83, 70, 55, 50, 117]
    colors = [NAVY, NAVY, NAVY, ACCENT, ACCENT, ACCENT, GREY]
    bars = ax.bar(regions, counts, color=colors, edgecolor="white", linewidth=2)
    ax.set_ylabel("Количество барбершопов", fontsize=11)
    ax.set_title("Распределение барбершопов по регионам UZ\n(всего 577, +18.9% г/г)", fontsize=12, fontweight="bold")
    for bar, val in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width()/2, val + 2, f"{val}", ha="center", fontsize=10, fontweight="bold")
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    save(fig, "barbers_by_region.png")


# 9. Unit-economics pie
def unit_economics(title: str, arpu: int, cac: int, server: int, support: int, marketing: int, profit: int, fname: str) -> None:
    fig, ax = plt.subplots(figsize=(8, 6))
    labels = [f"Твоя маржа\n{profit}к сум", f"Маркетинг\n{marketing}к сум", f"Сервер+инфра\n{server}к сум", f"Поддержка\n{support}к сум", f"CAC\n{cac}к сум"]
    sizes = [profit, marketing, server, support, cac]
    colors = [GREEN, ACCENT, NAVY, "#8cb4cf", RED]
    explode = [0.05, 0, 0, 0, 0]
    ax.pie(sizes, labels=labels, colors=colors, autopct="%1.0f%%", startangle=90, explode=explode, textprops={"fontsize": 10, "fontweight": "bold"}, wedgeprops={"edgecolor": "white", "linewidth": 2})
    ax.set_title(f"{title}\nARPU = {arpu}к сум/мес (на 1 клиенте)", fontsize=12, fontweight="bold")
    save(fig, fname)


if __name__ == "__main__":
    # Общие
    beauty_market_growth()
    competitors_price()
    messengers_uz()
    barbers_by_region()

    # Beauty-специфика
    tam_sam_som("Beauty-рынок UZ: воронка захвата",
                tam=10000, sam=3500, som=200,
                fname="tam_sam_som_beauty.png")
    mrr_forecast("Прогноз MRR салонов красоты (18 мес)",
                 conservative_end=10, realistic_end=30, optimistic_end=62,
                 fname="mrr_forecast_beauty.png")
    break_even("Break-even: салоны красоты",
               monthly_fixed=3, arpu_k_sum=150,
               fname="break_even_beauty.png")
    roadmap("roadmap_beauty.png")
    unit_economics("Unit-economics: салоны красоты",
                   arpu=150, cac=30, server=8, support=12, marketing=25, profit=75,
                   fname="unit_economics_beauty.png")

    # Barber-специфика
    tam_sam_som("Барбершопы UZ: воронка захвата",
                tam=2000, sam=800, som=80,
                fname="tam_sam_som_barbers.png")
    mrr_forecast("Прогноз MRR барбершопов (18 мес)",
                 conservative_end=6, realistic_end=18, optimistic_end=38,
                 fname="mrr_forecast_barbers.png")
    break_even("Break-even: барбершопы",
               monthly_fixed=3, arpu_k_sum=120,
               fname="break_even_barbers.png")
    roadmap("roadmap_barbers.png")
    unit_economics("Unit-economics: барбершопы",
                   arpu=120, cac=35, server=8, support=12, marketing=20, profit=45,
                   fname="unit_economics_barbers.png")

    print("OK: все графики сохранены в", OUT)
