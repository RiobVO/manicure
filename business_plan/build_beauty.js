// Бизнес-план: Telegram-бот для салонов красоты в Узбекистане
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun,
  AlignmentType, LevelFormat, HeadingLevel, BorderStyle, WidthType, ShadingType,
  ExternalHyperlink, PageBreak, TabStopType, TabStopPosition,
} = require("docx");

const CHARTS = path.join(__dirname, "charts");
const NAVY = "1e3a5f";
const ACCENT = "c9a961";
const GREEN = "4a7c59";
const RED = "a84444";
const LIGHT = "e8eef5";
const DARK = "2c2c2c";

const border = { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };

const TABLE_W = 9360;

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    children: [new TextRun({ text, color: NAVY, bold: true, size: 36 })],
    spacing: { before: 320, after: 200 },
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    children: [new TextRun({ text, color: NAVY, bold: true, size: 28 })],
    spacing: { before: 260, after: 140 },
  });
}
function h3(text) {
  return new Paragraph({
    children: [new TextRun({ text, color: ACCENT, bold: true, size: 24 })],
    spacing: { before: 200, after: 100 },
  });
}
function p(text, opts = {}) {
  return new Paragraph({
    children: [new TextRun({ text, size: 22, color: DARK, ...opts })],
    spacing: { after: 120 },
    alignment: opts.align || AlignmentType.JUSTIFIED,
  });
}
function pRuns(runs, opts = {}) {
  return new Paragraph({
    children: runs,
    spacing: { after: 120 },
    alignment: opts.align || AlignmentType.JUSTIFIED,
  });
}
function run(text, opts = {}) {
  return new TextRun({ text, size: 22, color: DARK, ...opts });
}
function bullet(text) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    children: [new TextRun({ text, size: 22, color: DARK })],
    spacing: { after: 80 },
  });
}
function bulletRuns(runs) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    children: runs,
    spacing: { after: 80 },
  });
}
function numbered(text) {
  return new Paragraph({
    numbering: { reference: "numbers", level: 0 },
    children: [new TextRun({ text, size: 22, color: DARK })],
    spacing: { after: 80 },
  });
}
function image(fname, w = 580, h = 320) {
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 160, after: 200 },
    children: [new ImageRun({
      type: "png",
      data: fs.readFileSync(path.join(CHARTS, fname)),
      transformation: { width: w, height: h },
      altText: { title: fname, description: fname, name: fname },
    })],
  });
}
function caption(text) {
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 240 },
    children: [new TextRun({ text, size: 18, color: "666666", italics: true })],
  });
}
function cell(text, opts = {}) {
  const widthDxa = opts.width || Math.floor(TABLE_W / 4);
  return new TableCell({
    borders,
    width: { size: widthDxa, type: WidthType.DXA },
    shading: opts.fill ? { fill: opts.fill, type: ShadingType.CLEAR } : undefined,
    margins: { top: 100, bottom: 100, left: 140, right: 140 },
    verticalAlign: "center",
    children: [new Paragraph({
      alignment: opts.center ? AlignmentType.CENTER : AlignmentType.LEFT,
      children: [new TextRun({
        text,
        size: opts.size || 20,
        bold: !!opts.bold,
        color: opts.color || DARK,
      })],
    })],
  });
}
function table(columnWidths, rows) {
  return new Table({
    width: { size: TABLE_W, type: WidthType.DXA },
    columnWidths,
    rows: rows.map(r => new TableRow({ children: r })),
  });
}
function callout(text, color = ACCENT) {
  return new Table({
    width: { size: TABLE_W, type: WidthType.DXA },
    columnWidths: [TABLE_W],
    rows: [new TableRow({
      children: [new TableCell({
        borders: {
          top: { style: BorderStyle.SINGLE, size: 4, color },
          bottom: { style: BorderStyle.SINGLE, size: 4, color },
          left: { style: BorderStyle.SINGLE, size: 24, color },
          right: { style: BorderStyle.SINGLE, size: 4, color },
        },
        width: { size: TABLE_W, type: WidthType.DXA },
        shading: { fill: LIGHT, type: ShadingType.CLEAR },
        margins: { top: 180, bottom: 180, left: 260, right: 180 },
        children: [new Paragraph({
          children: [new TextRun({ text, size: 22, color: DARK, italics: true })],
        })],
      })],
    })],
  });
}
function link(text, url) {
  return new Paragraph({
    spacing: { after: 80 },
    children: [
      new TextRun({ text: "• ", size: 20, color: DARK }),
      new ExternalHyperlink({
        children: [new TextRun({ text, size: 20, color: "0563C1", underline: { type: "single" } })],
        link: url,
      }),
    ],
  });
}
function spacer() {
  return new Paragraph({ children: [new TextRun({ text: "", size: 2 })], spacing: { after: 120 } });
}
function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

// ===== Документ =====

const children = [];

// --- COVER ---
children.push(
  new Paragraph({ children: [new TextRun({ text: "", size: 2 })], spacing: { before: 2400 } }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 200 },
    children: [new TextRun({ text: "БИЗНЕС-ПЛАН", size: 56, bold: true, color: NAVY })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 200 },
    children: [new TextRun({ text: "Telegram-SaaS для салонов красоты", size: 40, bold: true, color: ACCENT })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 1600 },
    children: [new TextRun({ text: "Узбекистан · маникюр, ногтевой сервис, бровисты", size: 28, color: "555555", italics: true })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 140 },
    children: [new TextRun({ text: "Документ #1 из 2", size: 22, color: "888888" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 1800 },
    children: [new TextRun({ text: "Подготовлено: апрель 2026", size: 22, color: "888888" })],
  }),
  pageBreak(),
);

// --- EXECUTIVE SUMMARY ---
children.push(h1("1. Краткая сводка (Executive Summary)"));
children.push(callout(
  "Вердикт: да, на этом можно подняться. Редкое сочетание факторов — рынок, канал, налоги, вакуум конкурентов — делает UZ одним из лучших рынков СНГ для Telegram-first SaaS в бьюти.",
  GREEN,
));
children.push(spacer());
children.push(h3("Почему именно сейчас и именно ты"));
children.push(bullet("Beauty-рынок UZ растёт +28% в год — ненасыщенный, молодой, открытый к технологиям."));
children.push(bullet("Telegram — 88% аудитории UZ. Почти монополия. В РФ/Казахстане такого нет."));
children.push(bullet("Конкуренты (YClients, Altegio) не локализованы под UZ, не принимают Click/Payme, дороги для микросегмента."));
children.push(bullet("Налоговый режим IT Park Uzbekistan: 0% налога на прибыль, 0% НДС на экспорт, 7.5% НДФЛ — продлён до 2040 года."));
children.push(bullet("У тебя уже есть рабочий MVP (8000 строк кода, полный функционал). Экономия 1.5–2 месяцев разработки на старте."));

children.push(h3("Ключевые цифры"));
children.push(table(
  [Math.floor(TABLE_W * 0.55), Math.floor(TABLE_W * 0.45)],
  [
    [cell("Показатель", { bold: true, fill: NAVY, color: "FFFFFF", width: Math.floor(TABLE_W * 0.55) }), cell("Значение", { bold: true, fill: NAVY, color: "FFFFFF", width: Math.floor(TABLE_W * 0.45) })],
    [cell("Оборот отрасли UZ (2024)", { width: Math.floor(TABLE_W * 0.55) }), cell("4.58 трлн сум (~ 31.8 млрд ₽)", { width: Math.floor(TABLE_W * 0.45) })],
    [cell("Рост г/г", { width: Math.floor(TABLE_W * 0.55), fill: LIGHT }), cell("+28%", { width: Math.floor(TABLE_W * 0.45), fill: LIGHT, bold: true, color: GREEN })],
    [cell("Салонов + частных мастеров в UZ", { width: Math.floor(TABLE_W * 0.55) }), cell("~ 8 000 – 12 000 точек", { width: Math.floor(TABLE_W * 0.45) })],
    [cell("Проникновение Telegram", { width: Math.floor(TABLE_W * 0.55), fill: LIGHT }), cell("88% аудитории", { width: Math.floor(TABLE_W * 0.45), fill: LIGHT, bold: true })],
    [cell("Реалистичный MRR за 18 мес", { width: Math.floor(TABLE_W * 0.55) }), cell("30 млн сум (~ 230 тыс ₽)", { width: Math.floor(TABLE_W * 0.45), bold: true, color: NAVY })],
    [cell("Потолок по формуле 20×MRR (цена продажи)", { width: Math.floor(TABLE_W * 0.55), fill: LIGHT }), cell("~ 600 млн сум (~ 4.6 млн ₽)", { width: Math.floor(TABLE_W * 0.45), fill: LIGHT, bold: true, color: ACCENT })],
    [cell("Налог для ИП/самозанятого с 2026", { width: Math.floor(TABLE_W * 0.55) }), cell("1% с оборота", { width: Math.floor(TABLE_W * 0.45) })],
    [cell("Инвестиции на старт", { width: Math.floor(TABLE_W * 0.55), fill: LIGHT }), cell("0 – 5 млн сум (твоё время + сервер)", { width: Math.floor(TABLE_W * 0.45), fill: LIGHT })],
  ],
));
children.push(pageBreak());

// --- МАКРОКАРТИНА РЫНКА ---
children.push(h1("2. Макрокартина рынка"));

children.push(h2("2.1. Размер и рост"));
children.push(p("По данным Госкомитета статистики Узбекистана, оборот парикмахерских и салонов красоты составил 4.58 трлн сум в 2024 году против 3.57 трлн в 2023. Это рост +28% год к году — аномально высокая динамика, свидетельствующая о ненасыщенном рынке."));
children.push(image("beauty_market_growth.png"));
children.push(caption("Рис. 1. Динамика оборота парикмахерских и салонов красоты UZ. Прогноз основан на сохранении темпа +28%."));

children.push(h2("2.2. География"));
children.push(p("Ташкент формирует 18–22% отраслевого оборота (838.7 млрд сум за 10 мес. 2022). Остальные центры — Самарканд, Андижан, Фергана, Наманган. В регионах проникновение CRM минимально, что открывает окно для продукта с узбекской локализацией."));

children.push(h2("2.3. Канал продаж: Telegram"));
children.push(p("Telegram — де-факто национальный канал коммуникаций в Узбекистане. 88% аудитории активно используют мессенджер, тогда как WhatsApp — всего 18%. В Казахстане картина зеркальна (WhatsApp 83%). Это означает, что Telegram-first продукт попадает в основной канал почти 100% целевой аудитории UZ."));
children.push(image("messengers_uz.png", 520, 320));
children.push(caption("Рис. 2. Проникновение мессенджеров в Узбекистане (Central Asia Barometer, 2025)."));
children.push(pageBreak());

// --- КОНКУРЕНТЫ ---
children.push(h1("3. Конкурентный анализ"));
children.push(p("Проанализировано 7 игроков на рынке CRM и систем онлайн-записи для салонов. Ключевой вывод: в микросегменте (1–5 сотрудников) рынок фактически пустой."));

children.push(h2("3.1. Сравнительная таблица"));
const cwCompetitors = [1800, 1600, 1700, 1500, 2760];
children.push(table(
  cwCompetitors,
  [
    [
      cell("Игрок", { bold: true, fill: NAVY, color: "FFFFFF", width: cwCompetitors[0] }),
      cell("Цена, сум/мес", { bold: true, fill: NAVY, color: "FFFFFF", width: cwCompetitors[1] }),
      cell("Узб. язык", { bold: true, fill: NAVY, color: "FFFFFF", width: cwCompetitors[2] }),
      cell("Click/Payme", { bold: true, fill: NAVY, color: "FFFFFF", width: cwCompetitors[3] }),
      cell("Слабости", { bold: true, fill: NAVY, color: "FFFFFF", width: cwCompetitors[4] }),
    ],
    [
      cell("YClients", { width: cwCompetitors[0], bold: true }),
      cell("125 – 420 тыс", { width: cwCompetitors[1] }),
      cell("Нет", { width: cwCompetitors[2], color: RED }),
      cell("Нет", { width: cwCompetitors[3], color: RED }),
      cell("Дорого для 1-3 сотр.; оплата в рублях; тех.поддержка из РФ", { width: cwCompetitors[4] }),
    ],
    [
      cell("Altegio", { width: cwCompetitors[0], bold: true, fill: LIGHT }),
      cell("По запросу ($)", { width: cwCompetitors[1], fill: LIGHT }),
      cell("Нет", { width: cwCompetitors[2], color: RED, fill: LIGHT }),
      cell("Только Uzum Bank", { width: cwCompetitors[3], fill: LIGHT, color: ACCENT }),
      cell("Непрозрачные цены; оплата в валюте; общая с YClients родословная", { width: cwCompetitors[4], fill: LIGHT }),
    ],
    [
      cell("DIKIDI", { width: cwCompetitors[0], bold: true }),
      cell("Free + модули", { width: cwCompetitors[1] }),
      cell("Нет", { width: cwCompetitors[2], color: RED }),
      cell("Нет", { width: cwCompetitors[3], color: RED }),
      cell("Слабая аналитика; не тянет сети", { width: cwCompetitors[4] }),
    ],
    [
      cell("Fresha", { width: cwCompetitors[0], bold: true, fill: LIGHT }),
      cell("Free + комиссия", { width: cwCompetitors[1], fill: LIGHT }),
      cell("Нет", { width: cwCompetitors[2], color: RED, fill: LIGHT }),
      cell("Нет (Visa/MC)", { width: cwCompetitors[3], color: RED, fill: LIGHT }),
      cell("Карточный эквайринг не работает в UZ", { width: cwCompetitors[4], fill: LIGHT }),
    ],
    [
      cell("Локальные UZ-CRM", { width: cwCompetitors[0], bold: true }),
      cell("—", { width: cwCompetitors[1] }),
      cell("—", { width: cwCompetitors[2] }),
      cell("—", { width: cwCompetitors[3] }),
      cell("Сильных локальных игроков не найдено (вакуум)", { width: cwCompetitors[4] }),
    ],
    [
      cell("ТВОЙ ПРОДУКТ", { width: cwCompetitors[0], bold: true, fill: GREEN, color: "FFFFFF" }),
      cell("50 – 400 тыс", { width: cwCompetitors[1], fill: GREEN, color: "FFFFFF", bold: true }),
      cell("ДА", { width: cwCompetitors[2], fill: GREEN, color: "FFFFFF", bold: true }),
      cell("Нативно", { width: cwCompetitors[3], fill: GREEN, color: "FFFFFF", bold: true }),
      cell("Telegram-first, локализация, низкая цена", { width: cwCompetitors[4], fill: GREEN, color: "FFFFFF" }),
    ],
  ],
));

children.push(spacer());
children.push(image("competitors_price.png", 560, 280));
children.push(caption("Рис. 3. Сравнение цен: твои тарифы против конкурентов."));

children.push(h2("3.2. 4 дыры в рынке"));
children.push(pRuns([run("Дыра #1 — Платежи. ", { bold: true, color: RED }), run("Никто из крупных не принимает Click/Payme нативно. Это главный канал расчётов в UZ. Нативная интеграция — твоё УТП.")]));
children.push(pRuns([run("Дыра #2 — SMS-экономика. ", { bold: true, color: RED }), run("SMS в UZ стоят 200–400 сум/шт. Салон шлёт 400+ SMS/мес = 80–160 тыс сум. Telegram — бесплатно. Продукт окупается только на экономии.")]));
children.push(pRuns([run("Дыра #3 — Язык. ", { bold: true, color: RED }), run("Ни у одного игрока нет узбекского UI. В Ташкенте терпимо, в регионах — блокер продаж.")]));
children.push(pRuns([run("Дыра #4 — Микросегмент. ", { bold: true, color: RED }), run("YClients для частного мастера = 190 тыс сум/мес (4–6% оборота). Продукта за 50–80 тыс нет на рынке.")]));
children.push(pageBreak());

// --- РАЗМЕР ВОЗМОЖНОСТИ ---
children.push(h1("4. TAM / SAM / SOM — потенциал захвата"));
children.push(p("Потенциал рынка разбит на три уровня: TAM (весь рынок), SAM (часть, которую можно обслужить технически) и SOM (часть, которую реально захватить)."));
children.push(image("tam_sam_som_beauty.png", 560, 300));
children.push(caption("Рис. 4. Воронка от общего рынка до реалистичного захвата за 18 месяцев."));

children.push(h2("4.1. Расчёт"));
children.push(bullet("TAM: ~10 000 салонов + частных мастеров в UZ (оценка по каталогам 2ГИС, salon.uz, Instagram)."));
children.push(bullet("SAM: ~3 500 точек в Ташкенте + крупных областных центрах, имеющих смартфон и Telegram."));
children.push(bullet("SOM: ~200 клиентов (5.7% SAM) за 18 месяцев — консервативная цель при правильном маркетинге."));

children.push(h2("4.2. Деньги на потолке"));
children.push(p("Если гипотетически все 10 000 точек платят 300 тыс сум/мес — потолок выручки отрасли ≈ 3 млрд сум/мес (~23 млн ₽/мес). Ты не возьмёшь всех, но даже 3% = 90 млн сум/мес (~690 тыс ₽/мес)."));
children.push(pageBreak());

// --- ПРОДУКТ ---
children.push(h1("5. Продукт"));
children.push(h2("5.1. Что есть сейчас (актив)"));
children.push(bullet("~8000 строк Python, aiogram 3, SQLite + APScheduler — рабочий MVP."));
children.push(bullet("Клиентский поток: выбор услуги → мастер → дата → время → профиль → подтверждение."));
children.push(bullet("Админ-кабинет: услуги, мастера, блокировки, статистика, XLSX-экспорт, настройки графика."));
children.push(bullet("Планировщик напоминаний за 24ч и 2ч с дедупликацией."));
children.push(bullet("Отзывы с рейтингом, мультимастерность, runtime-админы."));
children.push(bullet("~1200 строк тестов."));

children.push(h2("5.2. Что нужно сделать до продаж"));
children.push(h3("Критично (блокеры)"));
children.push(numbered("Узбекская локализация UI (латиница + кириллица)."));
children.push(numbered("Интеграция Click/Payme — приём оплаты депозита от клиента."));
children.push(numbered("Multi-tenancy: один процесс обслуживает N салонов."));
children.push(numbered("Веб-админка (FastAPI + Jinja или React) для настройки без разработчика."));
children.push(numbered("Убрать из репозитория manicure.db, __pycache__, .wal-файлы."));

children.push(h3("Можно отложить"));
children.push(bullet("Интеграция с Instagram (лиды из DM)."));
children.push(bullet("Мобильное приложение для мастера."));
children.push(bullet("Сложная сквозная аналитика."));

children.push(h2("5.3. Roadmap"));
children.push(image("roadmap_beauty.png", 600, 280));
children.push(caption("Рис. 5. Этапы развития на 18 месяцев."));
children.push(pageBreak());

// --- ЦЕНЫ ---
children.push(h1("6. Ценовая стратегия"));
children.push(p("Позиционирование — Telegram-бот с узбекским UI и оплатой Click/Payme от 50 тыс сум/мес. Прямая конкуренция с YClients на сегменте сетей не нужна — забираем «хвост» рынка, который им невыгоден."));

children.push(h2("6.1. Тарифная сетка"));
const cwTariff = [1400, 1800, 1760, 1400, 3000];
children.push(table(
  cwTariff,
  [
    [
      cell("Тариф", { bold: true, fill: NAVY, color: "FFFFFF", width: cwTariff[0] }),
      cell("Цена, сум/мес", { bold: true, fill: NAVY, color: "FFFFFF", width: cwTariff[1] }),
      cell("Для кого", { bold: true, fill: NAVY, color: "FFFFFF", width: cwTariff[2] }),
      cell("Мастеров", { bold: true, fill: NAVY, color: "FFFFFF", width: cwTariff[3] }),
      cell("Что входит", { bold: true, fill: NAVY, color: "FFFFFF", width: cwTariff[4] }),
    ],
    [
      cell("Free (trial)", { bold: true, width: cwTariff[0] }),
      cell("0 (14 дней)", { width: cwTariff[1], bold: true, color: GREEN }),
      cell("Новые", { width: cwTariff[2] }),
      cell("1", { width: cwTariff[3], center: true }),
      cell("Базовый бот, до 50 записей/мес", { width: cwTariff[4] }),
    ],
    [
      cell("Solo", { bold: true, width: cwTariff[0], fill: LIGHT }),
      cell("50 тыс (~325₽)", { width: cwTariff[1], fill: LIGHT, bold: true }),
      cell("Частные мастера", { width: cwTariff[2], fill: LIGHT }),
      cell("1", { width: cwTariff[3], center: true, fill: LIGHT }),
      cell("Неограниченно записей, напоминания, профили клиентов", { width: cwTariff[4], fill: LIGHT }),
    ],
    [
      cell("Studio", { bold: true, width: cwTariff[0] }),
      cell("150 тыс (~975₽)", { width: cwTariff[1], bold: true }),
      cell("Микросалоны", { width: cwTariff[2] }),
      cell("до 5", { width: cwTariff[3], center: true }),
      cell("+ Click/Payme, экспорт, аналитика, блокировки", { width: cwTariff[4] }),
    ],
    [
      cell("Pro", { bold: true, width: cwTariff[0], fill: LIGHT }),
      cell("400 тыс (~2 600₽)", { width: cwTariff[1], fill: LIGHT, bold: true, color: ACCENT }),
      cell("Сети и крупные салоны", { width: cwTariff[2], fill: LIGHT }),
      cell("до 15 + филиалы", { width: cwTariff[3], center: true, fill: LIGHT }),
      cell("+ роли, несколько филиалов, API, приоритетная поддержка", { width: cwTariff[4], fill: LIGHT }),
    ],
  ],
));
children.push(spacer());
children.push(callout("Правило продажи: на 14-дневном триале покажи салону отчёт — сколько SMS они не отправили и сколько денег сэкономили. Конверсия на этом аргументе выше, чем на любом рекламном тексте.", ACCENT));
children.push(pageBreak());

// --- ФИНМОДЕЛЬ ---
children.push(h1("7. Финансовая модель"));

children.push(h2("7.1. Unit-economics на одном клиенте"));
children.push(p("Тариф Studio (150 тыс сум/мес) как базовый. Все расходы — средние месячные на одного клиента."));
children.push(image("unit_economics_beauty.png", 460, 380));
children.push(caption("Рис. 6. Структура выручки на клиенте Studio. Чистая маржа ~50%."));

const cwUE = [3600, 2880, 2880];
children.push(table(
  cwUE,
  [
    [cell("Статья", { bold: true, fill: NAVY, color: "FFFFFF", width: cwUE[0] }), cell("сум/мес", { bold: true, fill: NAVY, color: "FFFFFF", width: cwUE[1] }), cell("% ARPU", { bold: true, fill: NAVY, color: "FFFFFF", width: cwUE[2] })],
    [cell("ARPU (тариф Studio)", { width: cwUE[0], bold: true }), cell("150 000", { width: cwUE[1], bold: true }), cell("100%", { width: cwUE[2], bold: true })],
    [cell("− CAC амортизированный (12 мес)", { width: cwUE[0], fill: LIGHT }), cell("30 000", { width: cwUE[1], fill: LIGHT, color: RED }), cell("20%", { width: cwUE[2], fill: LIGHT })],
    [cell("− Маркетинг (Instagram, таргет)", { width: cwUE[0] }), cell("25 000", { width: cwUE[1], color: RED }), cell("17%", { width: cwUE[2] })],
    [cell("− Поддержка", { width: cwUE[0], fill: LIGHT }), cell("12 000", { width: cwUE[1], fill: LIGHT, color: RED }), cell("8%", { width: cwUE[2], fill: LIGHT })],
    [cell("− Сервер + инфраструктура", { width: cwUE[0] }), cell("8 000", { width: cwUE[1], color: RED }), cell("5%", { width: cwUE[2] })],
    [cell("= Чистая маржа с клиента", { width: cwUE[0], bold: true, fill: GREEN, color: "FFFFFF" }), cell("75 000", { width: cwUE[1], bold: true, fill: GREEN, color: "FFFFFF" }), cell("50%", { width: cwUE[2], bold: true, fill: GREEN, color: "FFFFFF" })],
  ],
));

children.push(h2("7.2. Прогноз MRR на 18 месяцев"));
children.push(p("Три сценария с S-образной кривой адопции. Реалистичный строится на 200 клиентах к 18-му месяцу (60% Solo, 30% Studio, 10% Pro)."));
children.push(image("mrr_forecast_beauty.png", 600, 330));
children.push(caption("Рис. 7. Прогноз ежемесячной выручки (MRR). Реалистичный сценарий выделен тёмно-синим."));

children.push(h2("7.3. Break-even"));
children.push(p("Постоянные расходы на поддержание проекта — сервер, домен, сервисы аналитики, личный минимум — оценены в 3 млн сум/мес."));
children.push(image("break_even_beauty.png", 600, 300));
children.push(caption("Рис. 8. Точка безубыточности достигается примерно на 10-м месяце."));

children.push(h2("7.4. Итоговые деньги"));
const cwMoney = [3000, 3180, 3180];
children.push(table(
  cwMoney,
  [
    [cell("Сценарий", { bold: true, fill: NAVY, color: "FFFFFF", width: cwMoney[0] }), cell("MRR на 18 мес", { bold: true, fill: NAVY, color: "FFFFFF", width: cwMoney[1] }), cell("Стоимость продажи (20× MRR)", { bold: true, fill: NAVY, color: "FFFFFF", width: cwMoney[2] })],
    [cell("Консервативный", { width: cwMoney[0] }), cell("10 млн сум (77 тыс ₽)", { width: cwMoney[1] }), cell("200 млн сум (1.5 млн ₽)", { width: cwMoney[2] })],
    [cell("Реалистичный", { width: cwMoney[0], bold: true, fill: LIGHT }), cell("30 млн сум (230 тыс ₽)", { width: cwMoney[1], bold: true, fill: LIGHT, color: NAVY }), cell("600 млн сум (4.6 млн ₽)", { width: cwMoney[2], bold: true, fill: LIGHT, color: NAVY })],
    [cell("Оптимистичный (+KZ/KG)", { width: cwMoney[0] }), cell("62 млн сум (477 тыс ₽)", { width: cwMoney[1], color: ACCENT }), cell("1.24 млрд сум (9.5 млн ₽)", { width: cwMoney[2], color: ACCENT, bold: true })],
  ],
));
children.push(pageBreak());

// --- НАЛОГИ ---
children.push(h1("8. Налоги и вывод денег"));
children.push(h2("8.1. Самозанятый — старт"));
children.push(bullet("Регистрация онлайн через мобильное приложение «Soliq»."));
children.push(bullet("Лимит оборота: 100 млн сум/год (~770 тыс ₽)."));
children.push(bullet("Налог в 2025: фиксированный 1 БРВ/год = 412 000 сум (~2 700 ₽)."));
children.push(bullet("С 2026: ставка 1% с оборота до 1 млрд сум — уникально низкая по СНГ."));
children.push(bullet("Подходит для первых 12–18 месяцев, пока MRR не превысил лимит."));

children.push(h2("8.2. IT Park Uzbekistan — для масштаба"));
children.push(callout("IT Park — это единственное, что НЕЛЬЗЯ пропустить. Резиденты получают радикальные налоговые льготы, которых нет в РФ и нет у твоих конкурентов.", ACCENT));
children.push(bullet("0% налог на прибыль."));
children.push(bullet("0% НДС на экспорт услуг."));
children.push(bullet("7.5% НДФЛ (против 12% стандартных)."));
children.push(bullet("Льготы продлены до 1 января 2040 года (Указ №УП-157 от 14.10.2024)."));
children.push(bullet("Для экспорта в РФ/Казахстан — ты как резидент IT Park платишь 0% с экспортной выручки."));

children.push(h2("8.3. Приём денег"));
children.push(bullet("Click Business и Payme Business поддерживают рекуррентные B2B-списания. Комиссия мерчанту ~1%."));
children.push(bullet("Для юридических клиентов — расчётный счёт ИП + банковский перевод."));
children.push(bullet("Для экспорта в рубли — Payoneer или мультивалютные счета Kapitalbank / TBC / Anor."));
children.push(pageBreak());

// --- ГАРАНТИИ ---
children.push(h1("9. Гарантии выгоды — честно"));
children.push(callout("В бизнесе не существует абсолютных гарантий. Но можно построить цепочку конкретных цифр, где каждая независимо проверяема — и, если они сходятся, риск минимален.", RED));

children.push(h2("9.1. Минимальный сценарий провала (что ты теряешь)"));
children.push(bullet("Время на доработку MVP: 2–3 месяца по вечерам."));
children.push(bullet("Деньги: 2–3 млн сум (сервер, домен, реклама на первый пилот) = ~20 тыс ₽."));
children.push(bullet("Если за 6 месяцев не получилось продать ни одной платной подписки — откатываешься, теряешь ~время + 3 млн сум."));
children.push(pRuns([run("Это сопоставимо с месячной зарплатой Python-разработчика в Ташкенте (", {}), run("21 млн сум/год = 1.75 млн сум/мес", { bold: true }), run("). Риск маленький.")]));

children.push(h2("9.2. Почему «скорее выйдет, чем нет»"));
children.push(numbered("Каждая из 4 «дыр» в рынке — независимая. Закрывая любые 2 из 4 (например, uz-язык + Click/Payme), ты уже имеешь УТП, которого нет ни у кого."));
children.push(numbered("У тебя нет венчурного давления. Ты не «сжигаешь» $500k, тебе не нужны «hockey-stick» метрики. Тебе достаточно, чтобы 50 клиентов платили 150 тыс сум — это уже доход мидл-разработчика без налогов."));
children.push(numbered("Рост рынка +28% г/г — попутный ветер. Даже при нулевых усилиях по маркетингу часть салонов самостоятельно ищет CRM."));
children.push(numbered("У тебя географический бонус. Ты живёшь рядом с клиентами, понимаешь язык и культуру, конкуренты — нет."));
children.push(numbered("Код уже есть. Большинство конкурентов продукта ещё пишут MVP. Ты стартуешь с 2–3 месяцев форы."));

children.push(h2("9.3. Жёсткие признаки, что стоит выйти из проекта"));
children.push(bullet("3 месяца активных продаж → 0 платных клиентов (не trial). Значит либо продукт мимо, либо цена не та."));
children.push(bullet("Churn >10% в месяц после 6 месяцев работы. Значит салоны не получают ценности."));
children.push(bullet("CAC > 3×ARPU. Значит каналы привлечения не работают."));
children.push(pageBreak());

// --- ЧТО ДЕЛАТЬ ЗАВТРА УТРОМ ---
children.push(h1("10. Что делать завтра утром"));
children.push(callout("Цель ближайших 72 часов — не написать код, а подтвердить, что проблема реальная. Без этого любой код — пустой труд.", ACCENT));

children.push(h2("Неделя 1 — валидация"));
children.push(numbered("Пойди в 10 салонов в Ташкенте (маникюрных, до 5 мастеров) лично. Не продавай. Спрашивай: как записывают клиентов сейчас, сколько тратят на SMS, сколько no-show в месяц, что бесит."));
children.push(numbered("Запиши реплики дословно. Это сырьё для лендинга."));
children.push(numbered("Найди 3 салона, готовых на бесплатный пилот 2 месяца. Без этого дальше идти не нужно."));

children.push(h2("Неделя 2–3 — чистка кода"));
children.push(numbered("Удали manicure.db и __pycache__ из репо, добавь .gitignore."));
children.push(numbered("Напиши README с инструкцией запуска."));
children.push(numbered("Зафиксируй версии зависимостей в requirements.txt."));
children.push(numbered("Добавь узбекскую локализацию всех текстов бота."));

children.push(h2("Месяцы 2–3 — multi-tenancy и веб-админка"));
children.push(numbered("Добавь колонку salon_id во все таблицы БД."));
children.push(numbered("Сделай таблицу salons с bot_token, subscription_until."));
children.push(numbered("Подними FastAPI с веб-админкой (FastAPI + Jinja + HTMX — быстрый путь)."));
children.push(numbered("Интегрируй Payme Business для приёма подписок."));

children.push(h2("Месяцы 4–6 — пилот и первые платящие"));
children.push(numbered("Запусти 3–5 салонов на бесплатном тарифе, собери кейсы."));
children.push(numbered("Сделай лендинг с 3 кейсами («салон X сэкономил 120к сум/мес на SMS»)."));
children.push(numbered("Запусти Instagram-таргет на «владелец салона Ташкент» с бюджетом 1 млн сум/мес."));
children.push(numbered("Цель: 10 платящих клиентов к концу месяца 6."));

children.push(h2("Месяцы 7–12 — масштабирование"));
children.push(numbered("Наймите ассистента (5 млн сум/мес) для холодных продаж и поддержки."));
children.push(numbered("Оформление в IT Park Uzbekistan при MRR 10+ млн сум."));
children.push(numbered("Цель: 100 платящих клиентов к концу месяца 12."));
children.push(pageBreak());

// --- РИСКИ ---
children.push(h1("11. Риски и митигации"));
const cwRisk = [2600, 1700, 1700, 3360];
children.push(table(
  cwRisk,
  [
    [
      cell("Риск", { bold: true, fill: NAVY, color: "FFFFFF", width: cwRisk[0] }),
      cell("Вероятность", { bold: true, fill: NAVY, color: "FFFFFF", width: cwRisk[1] }),
      cell("Влияние", { bold: true, fill: NAVY, color: "FFFFFF", width: cwRisk[2] }),
      cell("Митигация", { bold: true, fill: NAVY, color: "FFFFFF", width: cwRisk[3] }),
    ],
    [
      cell("YClients локализуется под UZ", { width: cwRisk[0] }),
      cell("Средняя", { width: cwRisk[1] }),
      cell("Высокое", { width: cwRisk[2], color: RED }),
      cell("Окно 12–18 мес; занять микросегмент до входа крупных", { width: cwRisk[3] }),
    ],
    [
      cell("Частные мастера не платят (экономят)", { width: cwRisk[0], fill: LIGHT }),
      cell("Высокая", { width: cwRisk[1], fill: LIGHT, color: RED }),
      cell("Среднее", { width: cwRisk[2], fill: LIGHT }),
      cell("Фокус на микросалонах 3–5 сотр.; показывать ROI на SMS", { width: cwRisk[3], fill: LIGHT }),
    ],
    [
      cell("Санкции на Telegram в UZ", { width: cwRisk[0] }),
      cell("Низкая", { width: cwRisk[1] }),
      cell("Катастрофическое", { width: cwRisk[2], color: RED }),
      cell("Держать fallback-канал (WhatsApp Business API)", { width: cwRisk[3] }),
    ],
    [
      cell("Длинный цикл продаж", { width: cwRisk[0], fill: LIGHT }),
      cell("Высокая", { width: cwRisk[1], fill: LIGHT }),
      cell("Среднее", { width: cwRisk[2], fill: LIGHT }),
      cell("Free-тариф 14 дней; холодные продажи в ТЦ/Instagram-таргет", { width: cwRisk[3], fill: LIGHT }),
    ],
    [
      cell("Выгорание соло-фаундера", { width: cwRisk[0] }),
      cell("Высокая", { width: cwRisk[1], color: RED }),
      cell("Катастрофическое", { width: cwRisk[2], color: RED }),
      cell("Ограничить рабочие часы; нанять ассистента при MRR 10M сум", { width: cwRisk[3] }),
    ],
    [
      cell("Изменение налогов", { width: cwRisk[0], fill: LIGHT }),
      cell("Низкая", { width: cwRisk[1], fill: LIGHT }),
      cell("Среднее", { width: cwRisk[2], fill: LIGHT }),
      cell("IT Park даёт фиксацию условий до 2040", { width: cwRisk[3], fill: LIGHT }),
    ],
  ],
));
children.push(pageBreak());

// --- ИСТОЧНИКИ ---
children.push(h1("12. Источники"));
children.push(p("Все данные подтверждаются открытыми источниками. Ссылки активны на апрель 2026 года."));
children.push(h3("Статистика рынка"));
children.push(link("stat.uz — оборот парикмахерских и салонов UZ (4.58 трлн сум)", "https://stat.uz/ru/press-tsentr/novosti-goskomstata/31506-sartaroshxona-va-go-zallik-salonlari-xizmatlari-hajmi-4-579-7-mlrd-so-mni-tashkil-etdi-2"));
children.push(link("stat.uz — 281 тыс ИП в Узбекистане", "https://stat.uz/ru/press-tsentr/novosti-goskomstata/64997-zbekistonda-281-mingdan-zijod-yattlar-faoliyat-yuritmo-da-3"));
children.push(link("Statista — Beauty & Personal Care Uzbekistan $1.018B", "https://www.statista.com/outlook/cmo/beauty-personal-care/uzbekistan"));
children.push(link("Kursiv — Telegram 88% в UZ vs WhatsApp 83% в KZ", "https://kz.kursiv.media/en/2025-04-10/engk-yeri-digital-habits-why-kazakhstan-loves-whatsapp-and-uzbekistan-prefers-telegram/"));
children.push(link("CA Barometer — мессенджеры Центральной Азии", "https://ca-barometer.org/en/publications/which-messaging-apps-are-popular-in-uzbekistan-kyrgyzstan-and-kazakhstan"));
children.push(h3("Налоги и бизнес"));
children.push(link("IT Park Uzbekistan — налоговые льготы до 2040 (УП-157)", "https://buxgalter.uz/publish/doc/text203588_kakie_novye_lgoty_poluchili_rezidenty_it-parka"));
children.push(link("Buxgalter — самозанятые: лимит 100 млн сум", "https://buxgalter.uz/publish/doc/text210025_kak_oblagayutsya_dohody_samozanyatyh"));
children.push(link("Gazeta.uz — снижение налога до 1% с 2026", "https://www.gazeta.uz/ru/2025/08/11/business/"));
children.push(link("Gazeta.uz — смягчение закона о персональных данных", "https://www.gazeta.uz/ru/2026/03/27/personal-data/"));
children.push(h3("Конкуренты"));
children.push(link("YClients — тарифы и функционал", "https://www.yclients.com/beauty-salon"));
children.push(link("Altegio — тарифы", "https://alteg.io/en/info/pricing/"));
children.push(link("Сравнение Altegio и YClients 2026", "https://a2is.ru/catalog/rejting-crm-sistem/compare/altegio/yclients"));
children.push(link("Отзывы YClients (118 отзывов)", "https://crmindex.ru/products/yclients/reviews"));
children.push(h3("Рынок услуг UZ"));
children.push(link("Sevinch Nails Tashkent — реальный прайс маникюра", "https://sevinchnails.uz/stoimost-manikyura-pedikyura-price.html"));
children.push(link("Glassdoor — зарплаты Python Tashkent", "https://www.glassdoor.com/Salaries/tashkent-uzbekistan-python-developer-salary-SRCH_IL.0,19_IM3104_KO20,36.htm"));
children.push(link("Click/Payme — финтех-экосистема UZ", "https://themag.uz/ru/analitika/click-payme-uzum-bank-kuda-dvijetsya-fintekh/"));

// ===== DOC =====
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: NAVY },
        paragraph: { spacing: { before: 320, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: NAVY },
        paragraph: { spacing: { before: 260, after: 140 }, outlineLevel: 1 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    ],
  },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1200, right: 1200, bottom: 1200, left: 1200 } } },
    children,
  }],
});

Packer.toBuffer(doc).then(buf => {
  const out = path.join(__dirname, "01_Бизнес-план_Салоны_красоты_UZ.docx");
  fs.writeFileSync(out, buf);
  console.log("OK:", out);
});
