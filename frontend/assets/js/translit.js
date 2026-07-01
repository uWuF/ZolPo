// Hebrew → Latin / English helpers.
//
// These are a *fallback* for products that don't yet have a real `item_name_en`
// from the backend (Open Food Facts or a future manual/LLM pass). As soon as a
// product has a proper English name, app.js shows that verbatim and never calls
// the transliterator — so improving English is a data task, not a code task.
//
// Exposes: window.ZP.translitHe, window.ZP.translateProductName, window.ZP.BRAND_MAP
(function () {
  // Well-known Israeli brand names get exact matches first.
  const BRAND_MAP = {
    'תנובה': 'Tnuva', 'אסם': 'Osem', 'עלית': 'Elite', 'שטראוס': 'Strauss',
    'ברמן': 'Berman', 'נביעות': 'Neviot', 'מיה': 'Maya', 'מהדרין': 'Mehadrin',
    'יד מרדכי': 'Yad Mordechai', 'קוקה קולה': 'Coca-Cola', 'ברילה': 'Barilla',
    'סוגת': 'Sugat', 'דנונה': 'Danone', 'ניסין': 'Nissin', 'סטארקיסט': 'StarKist',
    'עוף טוב': 'Oaf Tov', 'כרמל': 'Carmel', 'יוטבתה': 'Yotvata', 'שופרסל': 'Shufersal',
    'רמי לוי': 'Rami Levy', 'נסטלה': 'Nestlé', 'הרדוף': 'Harduf',
    'מחלבת המושבה': 'Moshava Dairy', 'תרשיש': 'Tarshish', 'יופלה': 'Yoplait',
    "נייצ'ר ואלי": 'Nature Valley', 'ריטר': 'Ritter', 'לינדט': 'Lindt',
    'לא ידוע': '', 'לא ידועה': '',   // "unknown" — hide rather than show garbage
  };

  const HE_CHARS = {
    'א': '', 'ב': 'b', 'ג': 'g', 'ד': 'd', 'ה': 'h', 'ו': 'v', 'ז': 'z',
    'ח': 'ch', 'ט': 't', 'י': 'y', 'כ': 'k', 'ך': 'k', 'ל': 'l',
    'מ': 'm', 'ם': 'm', 'נ': 'n', 'ן': 'n', 'ס': 's', 'ע': '',
    'פ': 'p', 'ף': 'f', 'צ': 'tz', 'ץ': 'tz', 'ק': 'k', 'ר': 'r',
    'ש': 'sh', 'ת': 't',
  };

  function translitHe(str) {
    if (!str) return '';
    if (!/[א-ת]/.test(str)) return str; // already Latin
    const words = str.trim().split(/\s+/);
    const mapped = words.map(w => {
      if (BRAND_MAP[w]) return BRAND_MAP[w];
      let out = '';
      for (const ch of w) out += (HE_CHARS[ch] ?? (ch.match(/[a-zA-Z0-9%"'.,()\-]/) ? ch : ''));
      return out;
    });
    return mapped.join(' ').replace(/\b\w/g, c => c.toUpperCase()).replace(/\s+/g, ' ').trim();
  }

  // Common Hebrew food words -> English (word-by-word fallback translation).
  const HE_WORD_EN = {
    'חלב': 'Milk', 'חמאה': 'Butter', 'גבינה': 'Cheese', 'קוטג': 'Cottage', 'יוגורט': 'Yogurt',
    'שמנת': 'Cream', 'ביצים': 'Eggs', 'ביצה': 'Egg', 'לחם': 'Bread', 'פיתות': 'Pita',
    'חלה': 'Challah', 'שמן': 'Oil', 'זית': 'Olive', 'מים': 'Water', 'קפה': 'Coffee',
    'אורז': 'Rice', 'פסטה': 'Pasta', 'ספגטי': 'Spaghetti', 'פנה': 'Penne',
    'עוף': 'Chicken', 'פרגית': 'Chicken thighs', 'בשר': 'Meat', 'בקר': 'Beef',
    'טחון': 'Ground', 'דג': 'Fish', 'טונה': 'Tuna', 'סלמון': 'Salmon',
    'תפוח': 'Apple', 'בננה': 'Banana', 'תות': 'Strawberry', 'ענבים': 'Grapes',
    'אבטיח': 'Watermelon', 'עגבניה': 'Tomato', 'עגבניות': 'Tomatoes', 'מלפפון': 'Cucumber',
    'בצל': 'Onion', 'גזר': 'Carrot', 'ירקות': 'Vegetables', 'פירות': 'Fruits',
    'במבה': 'Bamba', 'ביסלי': 'Bisli', 'חטיף': 'Snack', 'עוגיות': 'Cookies',
    'שוקולד': 'Chocolate', 'סוכר': 'Sugar', 'קמח': 'Flour', 'מלח': 'Salt', 'פלפל': 'Pepper',
    'מיץ': 'Juice', 'קולה': 'Cola', 'סודה': 'Soda', 'נקטר': 'Nectar',
    'טרי': 'Fresh', 'קפוא': 'Frozen', 'עמיד': 'Long-life', 'מפוסטר': 'Pasteurized',
    'שלם': 'Whole', 'מלא': 'Full', 'דל': 'Low', 'ללא': 'Without', 'נטול': 'Free',
    'לקטוז': 'Lactose', 'שומן': 'Fat', 'מועשר': 'Enriched', 'אורגני': 'Organic',
    'פרוס': 'Sliced', 'גרוס': 'Grated', 'מיובש': 'Dried',
    'ק"ג': 'kg', 'גרם': 'g', 'מ"ל': 'ml', 'ליטר': 'L', 'יח': 'pc',
    'כתית': 'Extra Virgin', 'מעולה': 'Premium', 'ישראלי': 'Israeli',
    'הומוגני': 'Homogenized', 'בטעם': 'Flavored', 'טעם': 'Flavor',
    'וניל': 'Vanilla', 'לימון': 'Lemon', 'דבש': 'Honey', 'קרם': 'Cream', 'פרפה': 'Parfait',
    'מתוק': 'Sweet', 'חריף': 'Spicy', 'קל': 'Light',
    'עדין': 'Delicate', 'ביתי': 'Homestyle', 'טבעי': 'Natural',
    'מיוחד': 'Special', 'משפחה': 'Family', 'קטן': 'Small', 'גדול': 'Large',
    'אדום': 'Red', 'לבן': 'White', 'ירוק': 'Green', 'צהוב': 'Yellow',
    'חם': 'Hot', 'קר': 'Cold', 'מעושן': 'Smoked', 'מיונז': 'Mayonnaise',
    'רוטב': 'Sauce', 'מרק': 'Soup', 'קרקר': 'Cracker', 'דגני': 'Cereal',
    'שיבולת': 'Oat', 'שיפון': 'Rye', 'חיטה': 'Wheat', 'כוסמת': 'Buckwheat',
  };

  function translateProductName(str) {
    if (!str) return '';
    if (!/[א-ת]/.test(str)) return str; // already Latin
    return str.trim().split(/\s+/).map(w => {
      const clean = w.replace(/[.,'"?!]$/, '');
      return HE_WORD_EN[clean] ?? translitHe(w);
    }).join(' ').replace(/\s+/g, ' ').trim();
  }

  window.ZP = Object.assign(window.ZP || {}, { translitHe, translateProductName, BRAND_MAP });
})();
