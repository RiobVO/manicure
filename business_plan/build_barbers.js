// Бизнес-план: Telegram-бот для парикмахерских и барбершопов в Узбекистане
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun,
  AlignmentType, LevelFormat, HeadingLevel, BorderStyle, WidthType, ShadingType,
  ExternalHyperlink, PageBreak,
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
    children: [new TextRun({ text: "Telegram-SaaS для парикмахерских и барбершопов", size: 36, bold: true, color: ACCENT })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 1600 },
    children: [new TextRun({ text: "Узбекистан · мужские стрижки, парикмахерские, брадобреи", size: 26, color: "555555", italics: true })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 140 },
    children: [new TextRun({ text: "Документ #2 из 2", size: 22, color: "888888" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 1800 },
    children: [new TextRun({ text: "Подготовлено: апрель 2026", size: 22, color: "888888" })],
  }),
  pageBreak(),
);

// --- EXECUTIVE SUMMARY ---
children.push(h1("1. Краткая сводка"));
children.push(callout(
  "Вердикт: сегмент барбершопов в UZ даже более интересный, чем beauty. Рынок моложе (средний возраст точки 1.4 года), растёт +19% г/г, цифровизация почти нулевая (только 13% имеют даже сайт).",
  GREEN,
));
children.push(spacer());
children.push(h3("Ключевые отличия от сегмента beauty"));
children.push(bullet("Главная боль владельца — не «SMS дорого», а «клиент не приходит в субботу вечером». Решение — предоплата через Click/Payme при записи."));
children.push(bullet("93% точек — одиночные владельцы (не сети). Покупатель принимает решение сам, цикл продаж короткий."));
children.push(bullet("Рынок географически сбалансирован: Фергана (102), Самарканд (100), Ташкент (83). Регионы важнее столицы."));
children.push(bullet("Цена услуги выше: мужская стрижка 50–200 тыс сум, женская 60–300 тыс. No-show в subota стоит барберу прямо в рублях."));
children.push(bullet("Проникновение CRM ~0% (только у крупных сетей Big Bro, OldBoy). Конкуренция с твоим продуктом — бумажный журнал и Instagram DM."));

children.push(h3("Ключевые цифры"));
children.push(table(
  [Math.floor(TABLE_W * 0.55), Math.floor(TABLE_W * 0.45)],
  [
    [cell("Показатель", { bold: true, fill: NAVY, color: "FFFFFF", width: Math.floor(TABLE_W * 0.55) }), cell("Значение", { bold: true, fill: NAVY, color: "FFFFFF", width: Math.floor(TABLE_W * 0.45) })],
    [cell("Барбершопов в UZ (15.10.2025)", { width: Math.floor(TABLE_W * 0.55) }), cell("577", { width: Math.floor(TABLE_W * 0.45), bold: true })],
    [cell("Рост за 2 года", { width: Math.floor(TABLE_W * 0.55), fill: LIGHT }), cell("+18.89%", { width: Math.floor(TABLE_W * 0.45), fill: LIGHT, bold: true, color: GREEN })],
    [cell("Средний возраст точки", { width: Math.floor(TABLE_W * 0.55) }), cell("1 год 4 месяца", { width: Math.floor(TABLE_W * 0.45) })],
    [cell("Доля одиночных владельцев", { width: Math.floor(TABLE_W * 0.55), fill: LIGHT }), cell("93.24%", { width: Math.floor(TABLE_W * 0.45), fill: LIGHT })],
    [cell("Имеют собственный сайт", { width: Math.floor(TABLE_W * 0.55) }), cell("75 из 577 (13%)", { width: Math.floor(TABLE_W * 0.45), color: RED, bold: true })],
    [cell("Общий рынок парикмахерских + женских салонов UZ", { width: Math.floor(TABLE_W * 0.55), fill: LIGHT }), cell("≈ 2 000 точек (с женскими)", { width: Math.floor(TABLE_W * 0.45), fill: LIGHT })],
    [cell("Реалистичный MRR на 18 мес", { width: Math.floor(TABLE_W * 0.55) }), cell("18 млн сум (~140 тыс ₽)", { width: Math.floor(TABLE_W * 0.45), bold: true, color: NAVY })],
    [cell("Цена продажи бизнеса (20× MRR)", { width: Math.floor(TABLE_W * 0.55), fill: LIGHT }), cell("≈ 360 млн сум (~2.8 млн ₽)", { width: Math.floor(TABLE_W * 0.45), fill: LIGHT, bold: true, color: ACCENT })],
  ],
));
children.push(pageBreak());

// --- РЫНОК ---
children.push(h1("2. Рынок барбершопов Узбекистана"));

children.push(h2("2.1. Размер и динамика"));
children.push(p("По данным Rentech Digital на 15 октября 2025 года, в Узбекистане зарегистрировано 577 барбершопов. За два года рост +18.89%. Средний возраст точки — 1 год 4 месяца, что говорит о том, что рынок находится в ранней фазе роста. Большинство барбершопов открылись в последние 2 года."));

children.push(callout("Из 577 барбершопов только 75 имеют собственный сайт. 502 не имеют сайта вообще. Это означает, что базовый digital-инструмент отсутствует у 87% рынка — окно для онлайн-записи огромное.", ACCENT));

children.push(h2("2.2. География"));
children.push(image("barbers_by_region.png", 560, 300));
children.push(caption("Рис. 1. Распределение барбершопов по регионам UZ. Ташкент — только на 3-м месте."));
children.push(p("Неожиданно: Ташкент не лидирует по количеству барбершопов. Главные регионы — Ферганская область (102 точки) и Самаркандская (100). Это важный инсайт: стратегия «сначала Ташкент, потом регионы» для этого сегмента неверна. Первые клиенты логичнее искать в областных центрах, где конкуренция ниже, а YClients/Altegio практически не присутствуют."));

children.push(h2("2.3. Структура рынка"));
children.push(bullet("538 точек (93.24%) — solo, один владелец, одна точка."));
children.push(bullet("39 точек (6.76%) — сетевые: Big Bro, aVa, OldBoy, New Millennium, Bradobrey, Топор."));
children.push(p("Высокая доля solo-владельцев — преимущество для продажи: решение принимает один человек, без согласований, без отдела закупок. Цикл продаж короткий (1–3 звонка vs 2–3 месяца в корпоративных продажах)."));

children.push(h2("2.4. Цены услуг (Ташкент, 2025)"));
children.push(table(
  [Math.floor(TABLE_W / 2), Math.floor(TABLE_W / 2)],
  [
    [cell("Услуга", { bold: true, fill: NAVY, color: "FFFFFF", width: Math.floor(TABLE_W / 2) }), cell("Средняя цена, сум", { bold: true, fill: NAVY, color: "FFFFFF", width: Math.floor(TABLE_W / 2) })],
    [cell("Мужская стрижка (базовая)", { width: Math.floor(TABLE_W / 2) }), cell("50 000 – 100 000 (~325–650 ₽)", { width: Math.floor(TABLE_W / 2) })],
    [cell("Мужская стрижка + борода", { width: Math.floor(TABLE_W / 2), fill: LIGHT }), cell("120 000 – 200 000 (~780–1 300 ₽)", { width: Math.floor(TABLE_W / 2), fill: LIGHT })],
    [cell("Женская стрижка", { width: Math.floor(TABLE_W / 2) }), cell("60 000 – 150 000 (~390–975 ₽)", { width: Math.floor(TABLE_W / 2) })],
    [cell("Окрашивание", { width: Math.floor(TABLE_W / 2), fill: LIGHT }), cell("200 000 – 500 000 (~1 300–3 250 ₽)", { width: Math.floor(TABLE_W / 2), fill: LIGHT })],
  ],
));
children.push(spacer());
children.push(pRuns([run("Ключевая цифра: один no-show в субботу вечером = ", {}), run("100–200 тыс сум упущенной выручки", { bold: true, color: RED }), run(". 4–5 no-show в месяц = 600 тыс – 1 млн сум. Подписка 120 тыс/мес окупается за 1 предотвращённый no-show.")]));
children.push(pageBreak());

// --- TELEGRAM ---
children.push(h1("3. Почему Telegram-first работает именно для барберов"));
children.push(image("messengers_uz.png", 520, 320));
children.push(caption("Рис. 2. Проникновение мессенджеров в UZ."));

children.push(h2("3.1. Аудитория барберов — самая Telegram-ориентированная"));
children.push(bullet("Целевая аудитория мужских барбершопов — мужчины 18–45 лет. В UZ это самая активная группа в Telegram."));
children.push(bullet("Средняя длительность стрижки 30–45 минут позволяет планировать слоты точно — барбер теряет каждую минуту простоя."));
children.push(bullet("Instagram для барберов — главный канал маркетинга, но запись через DM — боль. Вручную администратор отвечает по 3 минуты на каждое сообщение."));
children.push(pageBreak());

// --- КОНКУРЕНТЫ ---
children.push(h1("4. Конкуренты и рыночный ландшафт"));

children.push(h2("4.1. Кто работает сейчас"));
const cwComp = [2200, 1800, 1700, 3660];
children.push(table(
  cwComp,
  [
    [
      cell("Конкурент", { bold: true, fill: NAVY, color: "FFFFFF", width: cwComp[0] }),
      cell("Где используют", { bold: true, fill: NAVY, color: "FFFFFF", width: cwComp[1] }),
      cell("Барберов в UZ", { bold: true, fill: NAVY, color: "FFFFFF", width: cwComp[2] }),
      cell("Ограничения", { bold: true, fill: NAVY, color: "FFFFFF", width: cwComp[3] }),
    ],
    [
      cell("Бумажный журнал", { width: cwComp[0], bold: true }),
      cell("Solo-барбершопы", { width: cwComp[1] }),
      cell("~ 400 (70%)", { width: cwComp[2], bold: true, color: RED }),
      cell("Нет напоминаний, нет защиты от no-show, нет статистики", { width: cwComp[3] }),
    ],
    [
      cell("Instagram DM", { width: cwComp[0], bold: true, fill: LIGHT }),
      cell("Молодые барберы", { width: cwComp[1], fill: LIGHT }),
      cell("~ 150 (26%)", { width: cwComp[2], fill: LIGHT }),
      cell("Ручная обработка, нет интеграции с календарём", { width: cwComp[3], fill: LIGHT }),
    ],
    [
      cell("YClients", { width: cwComp[0], bold: true }),
      cell("Сети 10+ сотр.", { width: cwComp[1] }),
      cell("~ 20 (3.5%)", { width: cwComp[2] }),
      cell("Дорого (190к+ сум), нет узб. языка, нет Click/Payme", { width: cwComp[3] }),
    ],
    [
      cell("Telegram-боты на заказ", { width: cwComp[0], bold: true, fill: LIGHT }),
      cell("Единичные", { width: cwComp[1], fill: LIGHT }),
      cell("~ 5", { width: cwComp[2], fill: LIGHT }),
      cell("Костыль без обновлений и поддержки", { width: cwComp[3], fill: LIGHT }),
    ],
    [
      cell("ТВОЙ ПРОДУКТ", { width: cwComp[0], bold: true, fill: GREEN, color: "FFFFFF" }),
      cell("Solo + микросети", { width: cwComp[1], fill: GREEN, color: "FFFFFF" }),
      cell("Цель 80 за 18 мес", { width: cwComp[2], fill: GREEN, color: "FFFFFF", bold: true }),
      cell("От 50к сум, узб. язык, Click/Payme, защита от no-show", { width: cwComp[3], fill: GREEN, color: "FFFFFF" }),
    ],
  ],
));
children.push(spacer());
children.push(image("competitors_price.png", 560, 280));
children.push(caption("Рис. 3. Сравнение цен: общая картина для сегмента beauty, ориентиры применимы и к барберам."));
children.push(pageBreak());

// --- TAM ---
children.push(h1("5. TAM / SAM / SOM"));
children.push(image("tam_sam_som_barbers.png", 560, 300));
children.push(caption("Рис. 4. Воронка возможностей для барбершопов UZ."));

children.push(bullet("TAM: ~2 000 точек (577 барбершопов + ~1 400 классических парикмахерских)."));
children.push(bullet("SAM: ~800 точек в 4 крупных регионах (Ташкент, Фергана, Самарканд, Андижан), имеющих Telegram и платёжеспособность."));
children.push(bullet("SOM: 80 клиентов (10% SAM) за 18 месяцев. Реалистично при правильном маркетинге."));

children.push(callout("Почему SOM выше, чем в beauty в процентах: барберы более однородны (мужские стрижки везде одинаковые), цикл продаж короче (1 владелец → 1 решение), главная боль (no-show) одинакова везде.", GREEN));
children.push(pageBreak());

// --- ПРОДУКТ ---
children.push(h1("6. Продукт: что изменить под барберов"));

children.push(h2("6.1. Специфические фичи, которые нужно добавить"));
children.push(numbered("Предоплата 20–30% стоимости стрижки при записи через Click/Payme. Главный аргумент продажи: «окупается за один предотвращённый no-show»."));
children.push(numbered("Быстрая запись в 1 клик: barber bot показывает ближайший свободный слот, клиент нажимает «беру» — всё."));
children.push(numbered("Фото мастера в карточке: у барберов выбор по мастеру критичнее, чем у маникюра. Instagram-стиль карточек."));
children.push(numbered("Автоматическое предложение следующей записи через 4 недели (средний интервал между стрижками)."));
children.push(numbered("Статистика «самые загруженные часы» и «процент no-show» — владельцу это важнее, чем общая выручка."));

children.push(h2("6.2. Что НЕ нужно делать"));
children.push(bullet("Сложные профили услуг с аддонами (как у маникюра). У барбера 3–5 базовых услуг."));
children.push(bullet("Длинные анкеты клиента. Мужики не заполняют анкеты. Имя + телефон — максимум."));
children.push(bullet("Сложная аналитика. Владельцу нужен один экран: «сколько записей на неделе + no-show %»."));

children.push(h2("6.3. Roadmap"));
children.push(image("roadmap_barbers.png", 600, 280));
children.push(caption("Рис. 5. Этапы развития продукта для сегмента барбершопов."));
children.push(pageBreak());

// --- ЦЕНЫ ---
children.push(h1("7. Ценовая стратегия"));
children.push(p("ARPU для барберов ниже, чем для beauty (меньше мастеров в среднем), но цикл продаж короче и churn ниже. Базовый тариф — 50 тыс сум (solo-барбер), флагман — 120 тыс сум (барбершоп 3–5 мастеров)."));

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
      cell("0 (30 дней)", { width: cwTariff[1], bold: true, color: GREEN }),
      cell("Новые барбершопы", { width: cwTariff[2] }),
      cell("до 2", { width: cwTariff[3], center: true }),
      cell("Полный функционал без ограничений — чтобы увидели no-show статистику", { width: cwTariff[4] }),
    ],
    [
      cell("Barber Solo", { bold: true, width: cwTariff[0], fill: LIGHT }),
      cell("50 тыс (~325₽)", { width: cwTariff[1], fill: LIGHT, bold: true }),
      cell("Барбер-одиночка", { width: cwTariff[2], fill: LIGHT }),
      cell("1", { width: cwTariff[3], center: true, fill: LIGHT }),
      cell("Запись, напоминания, Click/Payme", { width: cwTariff[4], fill: LIGHT }),
    ],
    [
      cell("Barber Shop", { bold: true, width: cwTariff[0] }),
      cell("120 тыс (~780₽)", { width: cwTariff[1], bold: true }),
      cell("Барбершоп", { width: cwTariff[2] }),
      cell("до 5", { width: cwTariff[3], center: true }),
      cell("+ предоплата за запись, статистика no-show, экспорт", { width: cwTariff[4] }),
    ],
    [
      cell("Barber Chain", { bold: true, width: cwTariff[0], fill: LIGHT }),
      cell("300 тыс (~1 950₽)", { width: cwTariff[1], fill: LIGHT, bold: true, color: ACCENT }),
      cell("Сеть с филиалами", { width: cwTariff[2], fill: LIGHT }),
      cell("до 15 + филиалы", { width: cwTariff[3], center: true, fill: LIGHT }),
      cell("+ несколько локаций, роли, сводная аналитика, API", { width: cwTariff[4], fill: LIGHT }),
    ],
  ],
));

children.push(spacer());
children.push(callout("Уникальное УТП барберам: «один предотвращённый no-show окупает подписку на 2 месяца». Реальный пример для лендинга: подписка Shop = 120к сум, средний no-show = 150к сум. Это математика, которую считают за 3 секунды.", ACCENT));
children.push(pageBreak());

// --- ФИНМОДЕЛЬ ---
children.push(h1("8. Финансовая модель"));

children.push(h2("8.1. Unit-economics"));
children.push(p("Базовый тариф — Barber Shop (120 тыс сум/мес). Расходы на клиента в среднем по портфелю."));
children.push(image("unit_economics_barbers.png", 460, 380));
children.push(caption("Рис. 6. Структура юнит-экономики барберского клиента."));

const cwUE = [3600, 2880, 2880];
children.push(table(
  cwUE,
  [
    [cell("Статья", { bold: true, fill: NAVY, color: "FFFFFF", width: cwUE[0] }), cell("сум/мес", { bold: true, fill: NAVY, color: "FFFFFF", width: cwUE[1] }), cell("% ARPU", { bold: true, fill: NAVY, color: "FFFFFF", width: cwUE[2] })],
    [cell("ARPU (тариф Barber Shop)", { width: cwUE[0], bold: true }), cell("120 000", { width: cwUE[1], bold: true }), cell("100%", { width: cwUE[2], bold: true })],
    [cell("− CAC амортизированный (12 мес)", { width: cwUE[0], fill: LIGHT }), cell("35 000", { width: cwUE[1], fill: LIGHT, color: RED }), cell("29%", { width: cwUE[2], fill: LIGHT })],
    [cell("− Маркетинг", { width: cwUE[0] }), cell("20 000", { width: cwUE[1], color: RED }), cell("17%", { width: cwUE[2] })],
    [cell("− Поддержка", { width: cwUE[0], fill: LIGHT }), cell("12 000", { width: cwUE[1], fill: LIGHT, color: RED }), cell("10%", { width: cwUE[2], fill: LIGHT })],
    [cell("− Сервер + инфраструктура", { width: cwUE[0] }), cell("8 000", { width: cwUE[1], color: RED }), cell("7%", { width: cwUE[2] })],
    [cell("= Чистая маржа с клиента", { width: cwUE[0], bold: true, fill: GREEN, color: "FFFFFF" }), cell("45 000", { width: cwUE[1], bold: true, fill: GREEN, color: "FFFFFF" }), cell("37%", { width: cwUE[2], bold: true, fill: GREEN, color: "FFFFFF" })],
  ],
));

children.push(h2("8.2. Прогноз MRR"));
children.push(image("mrr_forecast_barbers.png", 600, 330));
children.push(caption("Рис. 7. Прогноз MRR сегмента барбершопов. Реалистичный сценарий — 18 млн сум к месяцу 18."));

children.push(h2("8.3. Break-even"));
children.push(image("break_even_barbers.png", 600, 300));
children.push(caption("Рис. 8. Точка безубыточности ~11-й месяц."));

children.push(h2("8.4. Сценарии"));
const cwMoney = [3000, 3180, 3180];
children.push(table(
  cwMoney,
  [
    [cell("Сценарий", { bold: true, fill: NAVY, color: "FFFFFF", width: cwMoney[0] }), cell("MRR на 18 мес", { bold: true, fill: NAVY, color: "FFFFFF", width: cwMoney[1] }), cell("Стоимость (20× MRR)", { bold: true, fill: NAVY, color: "FFFFFF", width: cwMoney[2] })],
    [cell("Консервативный", { width: cwMoney[0] }), cell("6 млн сум (46 тыс ₽)", { width: cwMoney[1] }), cell("120 млн сум (920 тыс ₽)", { width: cwMoney[2] })],
    [cell("Реалистичный", { width: cwMoney[0], bold: true, fill: LIGHT }), cell("18 млн сум (140 тыс ₽)", { width: cwMoney[1], bold: true, fill: LIGHT, color: NAVY }), cell("360 млн сум (2.8 млн ₽)", { width: cwMoney[2], bold: true, fill: LIGHT, color: NAVY })],
    [cell("Оптимистичный", { width: cwMoney[0] }), cell("38 млн сум (290 тыс ₽)", { width: cwMoney[1], color: ACCENT }), cell("760 млн сум (5.8 млн ₽)", { width: cwMoney[2], color: ACCENT, bold: true })],
  ],
));

children.push(h2("8.5. Объединённая стратегия (beauty + barbers)"));
children.push(p("Ключевой инсайт: оба сегмента обслуживаются одним и тем же кодом. Функциональные различия (предоплата, интервалы между визитами, карточки мастеров) — это 2–3 недели доработки. Запуская оба вертикали параллельно, ты удваиваешь рынок почти без удвоения расходов."));
children.push(table(
  cwMoney,
  [
    [cell("Объединённо", { bold: true, fill: NAVY, color: "FFFFFF", width: cwMoney[0] }), cell("MRR на 18 мес", { bold: true, fill: NAVY, color: "FFFFFF", width: cwMoney[1] }), cell("Стоимость (20×)", { bold: true, fill: NAVY, color: "FFFFFF", width: cwMoney[2] })],
    [cell("Beauty + Barbers (реалистично)", { width: cwMoney[0], bold: true, fill: GREEN, color: "FFFFFF" }), cell("48 млн сум (370 тыс ₽)", { width: cwMoney[1], bold: true, fill: GREEN, color: "FFFFFF" }), cell("≈ 960 млн сум (~7.4 млн ₽)", { width: cwMoney[2], bold: true, fill: GREEN, color: "FFFFFF" })],
  ],
));
children.push(pageBreak());

// --- ЧТО ДЕЛАТЬ ---
children.push(h1("9. Что делать завтра утром"));

children.push(h2("Неделя 1 — интервью с 5 барберами"));
children.push(numbered("Зайди в 5 барбершопов (Big Bro, aVa, OldBoy и 2 solo). Представься «IT-парень, хочу сделать бот для записи, что вас бесит сейчас?»"));
children.push(numbered("Задай ровно три вопроса: (а) сколько no-show в неделю, (б) как узнают о записях, (в) сколько бы заплатили за автоматическое подтверждение с предоплатой."));
children.push(numbered("Запиши дословные реплики — это скрипт для лендинга."));

children.push(h2("Неделя 2–4 — адаптация MVP"));
children.push(numbered("Добавь модуль предоплаты через Click/Payme (это главное отличие от beauty-версии)."));
children.push(numbered("Упрости карточку услуги до 3 полей: название, цена, длительность."));
children.push(numbered("Добавь экран «no-show статистика» на главную админа."));
children.push(numbered("Узбекская локализация — латиница приоритет (молодые барберы читают чаще латиницу)."));

children.push(h2("Месяцы 2–4 — пилот"));
children.push(numbered("Найди 5 solo-барберов в разных районах Ташкента. Дай полный функционал бесплатно на 3 месяца в обмен на видео-отзыв."));
children.push(numbered("Через 30 дней — отчёт «сколько no-show вы предотвратили». Это становится основным материалом продаж."));

children.push(h2("Месяцы 5–12 — продажи в регионы"));
children.push(numbered("Фергана и Самарканд — главные точки роста (200+ барбершопов там)."));
children.push(numbered("Холодный обход: 5 барбершопов/день × 5 дней × 4 недели = 100 демо в месяц. Конверсия 10% = 10 клиентов."));
children.push(numbered("Партнёрство со школами парикмахеров в UZ — они рекомендуют софт выпускникам, получают %."));
children.push(pageBreak());

// --- ГАРАНТИИ ---
children.push(h1("10. Гарантии: честный разговор"));

children.push(callout("Гарантий в бизнесе нет. Но математика этого сегмента особенно убедительна из-за одной цифры: 1 no-show в субботу = 150 тыс сум. Подписка = 120 тыс сум. Продукт продаёт себя на калькуляторе.", RED));

children.push(h2("10.1. Почему это выгоднее beauty"));
children.push(bullet("Более короткий цикл продаж: solo-владелец = решение за 1 встречу."));
children.push(bullet("Сильнее ROI-аргумент: no-show считается в рублях, SMS — нет."));
children.push(bullet("Меньшая ценовая чувствительность: барбер зарабатывает 20–35 млн сум/мес, 120к на софт — копейки."));
children.push(bullet("Почти пустой рынок: 87% барбершопов не имеют даже сайта."));

children.push(h2("10.2. Почему это сложнее beauty"));
children.push(bullet("Меньше точек в абсолюте (577 vs ~10 000 в beauty)."));
children.push(bullet("География распределена, Ташкент не главный — нужны командировки в регионы."));
children.push(bullet("Барберы — менее «digital-native», чем ногтевые мастера (они младше, но меньше работают с софтом)."));

children.push(h2("10.3. Минимальный сценарий"));
children.push(p("Если за 12 месяцев работы удалось подключить только 20 клиентов со средним чеком 100 тыс сум — это 2 млн сум/мес (~15 тыс ₽). Проект не взлетел, но и не убыточен (постоянные расходы 3 млн сум/мес — убыток 1 млн/мес = 8 тыс ₽/мес). За год потеря сопоставима с 1 месяцем работы Python-разработчика в Ташкенте. Риск ограниченный."));
children.push(pageBreak());

// --- РИСКИ ---
children.push(h1("11. Риски"));
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
      cell("Барберы не хотят предоплату («отпугнёт клиентов»)", { width: cwRisk[0] }),
      cell("Средняя", { width: cwRisk[1] }),
      cell("Высокое", { width: cwRisk[2], color: RED }),
      cell("Делать фичу опциональной; показать кейсы салонов где предоплата подняла loyalty", { width: cwRisk[3] }),
    ],
    [
      cell("Сетевые игроки (Big Bro, OldBoy) выпустят свои боты", { width: cwRisk[0], fill: LIGHT }),
      cell("Средняя", { width: cwRisk[1], fill: LIGHT }),
      cell("Низкое", { width: cwRisk[2], fill: LIGHT }),
      cell("Они не продают свой бот конкурентам; наш рынок — solo-точки", { width: cwRisk[3], fill: LIGHT }),
    ],
    [
      cell("Мало точек в абсолюте (577)", { width: cwRisk[0] }),
      cell("Высокая", { width: cwRisk[1], color: RED }),
      cell("Среднее", { width: cwRisk[2] }),
      cell("Расширять до классических парикмахерских (1400+ точек), потом KZ", { width: cwRisk[3] }),
    ],
    [
      cell("Сезонность: летом меньше стрижек", { width: cwRisk[0], fill: LIGHT }),
      cell("Высокая", { width: cwRisk[1], fill: LIGHT }),
      cell("Низкое", { width: cwRisk[2], fill: LIGHT }),
      cell("Годовые подписки со скидкой 20% — сглаживают сезонность", { width: cwRisk[3], fill: LIGHT }),
    ],
    [
      cell("Низкая цифровая грамотность владельцев в регионах", { width: cwRisk[0] }),
      cell("Средняя", { width: cwRisk[1] }),
      cell("Среднее", { width: cwRisk[2] }),
      cell("Настройка под ключ за 200к сум разово; онбординг по видео", { width: cwRisk[3] }),
    ],
  ],
));
children.push(pageBreak());

// --- ИСТОЧНИКИ ---
children.push(h1("12. Источники"));
children.push(h3("Статистика барбершопов"));
children.push(link("Rentech Digital — 577 барбершопов в UZ, +18.89% г/г", "https://rentechdigital.com/smartscraper/business-report-details/list-of-barber-shops-in-uzbekistan"));
children.push(link("stat.uz — оборот парикмахерских и салонов 4.58 трлн сум", "https://stat.uz/ru/press-tsentr/novosti-goskomstata/31506-sartaroshxona-va-go-zallik-salonlari-xizmatlari-hajmi-4-579-7-mlrd-so-mni-tashkil-etdi-2"));
children.push(h3("Ценовые ориентиры"));
children.push(link("Big Bro — сеть мужских парикмахерских Ташкент", "https://tashkent.big-bro.pro/"));
children.push(link("aVa Barbershop — Ташкент", "https://avabarbershop.uz/"));
children.push(link("New Millennium Barbershop — премиум-сегмент", "https://nmbarbershop.uz/"));
children.push(link("OldBoy Barbershop Ташкент", "https://oldboybarbershop.com/uzbekistan/tashkent"));
children.push(h3("Мессенджеры и канал"));
children.push(link("Kursiv — Telegram 88% в UZ", "https://kz.kursiv.media/en/2025-04-10/engk-yeri-digital-habits-why-kazakhstan-loves-whatsapp-and-uzbekistan-prefers-telegram/"));
children.push(link("CA Barometer — мессенджеры ЦА", "https://ca-barometer.org/en/publications/which-messaging-apps-are-popular-in-uzbekistan-kyrgyzstan-and-kazakhstan"));
children.push(h3("Налоги и бизнес"));
children.push(link("IT Park Uzbekistan — льготы до 2040", "https://buxgalter.uz/publish/doc/text203588_kakie_novye_lgoty_poluchili_rezidenty_it-parka"));
children.push(link("Buxgalter — самозанятые лимит 100 млн сум", "https://buxgalter.uz/publish/doc/text210025_kak_oblagayutsya_dohody_samozanyatyh"));
children.push(link("Gazeta.uz — налог 1% с 2026", "https://www.gazeta.uz/ru/2025/08/11/business/"));
children.push(h3("Платежи"));
children.push(link("Click/Payme — финтех UZ", "https://themag.uz/ru/analitika/click-payme-uzum-bank-kuda-dvijetsya-fintekh/"));

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
  const out = path.join(__dirname, "02_Бизнес-план_Парикмахерские_UZ.docx");
  fs.writeFileSync(out, buf);
  console.log("OK:", out);
});
