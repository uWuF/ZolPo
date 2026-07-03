// Hebrew → Latin / English helpers.
//
// These are a *fallback* for products that don't yet have a real `item_name_en`
// from the backend (curated batches / future LLM pass). As soon as a product
// has a proper English name, app.js shows that verbatim and never calls the
// transliterator — so improving English is a data task, not a code task.
//
// Order of precedence inside the fallback:
//   1. PHRASE_MAP  — two-word phrases ("שיבולת שועל" → Oats)
//   2. BRAND_MAP   — brand names, transliterated WITH vowels (במבה → Bamba)
//   3. HE_WORD_EN  — generic product words, translated (יוגורט → Yogurt)
//   4. translitHe  — letter fallback for the rare residue
//
// Exposes: window.ZP.translitHe, window.ZP.translateProductName, window.ZP.BRAND_MAP

(function () {
  // Well-known brand names — always vocalized transliteration, never translated.
  const BRAND_MAP = {
    // Israeli dairy / food majors
    'תנובה': 'Tnuva', 'טרה': 'Tara', 'יטבתה': 'Yotvata', 'יוטבתה': 'Yotvata',
    'שטראוס': 'Strauss', 'אסם': 'Osem', 'עלית': 'Elite', 'תלמה': 'Telma',
    'זוגלובק': 'Zoglowek', 'טירת': 'Tirat', 'צבי': 'Zvi', 'סוגת': 'Sugat',
    'יכין': 'Yachin', 'עסיס': 'Assis', 'ויסוצקי': 'Wissotzky', 'עמק': 'Emek',
    'גד': 'Gad', 'סקי': 'Ski', 'גלבוע': 'Gilboa', 'מהדרין': 'Mehadrin',
    'הרדוף': 'Harduf', 'ברמן': 'Berman', 'אנגל': 'Angel', 'מעדנות': 'Maadanot',
    'זהבה': 'Zehava', 'האופה': 'HaOfe', 'כרמל': 'Carmel', 'תרשיש': 'Tarshish',
    'מחלבת המושבה': 'Moshava Dairy', 'שופרסל': 'Shufersal', 'רמי לוי': 'Rami Levy',
    'רמי': 'Rami', 'לוי': 'Levy', 'קרפור': 'Carrefour', 'מיה': 'Maya',
    'נביעות': 'Neviot', 'עדן': 'Eden', 'פריגת': 'Prigat', 'ספרינג': 'Spring',
    'טמפו': 'Tempo', 'מכבי': 'Maccabee', 'גולדסטאר': 'Goldstar',
    // snacks / sweets
    'במבה': 'Bamba', 'ביסלי': 'Bissli', 'אפרופו': 'Apropo', 'דובונים': 'Dubonim',
    'תפוצ\'יפס': 'Tapuchips', 'תפוציפס': 'Tapuchips', 'כיפלי': 'Kifli',
    'ציטוס': 'Cheetos', 'דוריטוס': 'Doritos', 'פופקו': 'Popco',
    'מקופלת': 'Mekupelet', 'פרה': 'Para', 'שוגי': 'Shugi', 'מגדים': 'Migdim',
    'קליק': 'Klik', 'טורטית': 'Tortit', 'ערגליות': 'Argaliot',
    'מילקי': 'Milky', 'דניאלה': 'Daniella', 'יולו': 'Yolo', 'אקטימל': 'Actimel',
    'שוקולית': 'Shokolit', 'עוגיות': 'Cookies',
    "בן אנד ג'ריס": "Ben & Jerry's", "בן & ג'ריס": "Ben & Jerry's",
    "בנג'ריס": "Ben & Jerry's", "בן אנד ג`ריס": "Ben & Jerry's",
    "בן אנד גריס": "Ben & Jerry's", "בנג׳ריס": "Ben & Jerry's",
    "בן&ג'ריס": "Ben & Jerry's", "בן&גריס": "Ben & Jerry's",
    'פיינט': 'Pint', 'פינט': 'Pint', 'גלידות': 'Ice Cream',
    'האגן דאז': 'Häagen-Dazs', 'מגנום': 'Magnum', 'קרלו': 'Karlo',
    'נסטלה': 'Nestlé', 'לוטוס': 'Lotus', 'קינדר': 'Kinder',
    'פררו': 'Ferrero', 'רושה': 'Rocher', 'לינדט': 'Lindt',
    'אלומות': 'Alumot', 'הולנד': 'Holland', 'אלופים': 'Alufim',
    'סמירנוף': 'Smirnoff', 'וויליפוד': 'Willi Food', 'ויליפוד': 'Willi Food',
    // international
    'קוקה קולה': 'Coca-Cola', 'פפסי': 'Pepsi', 'ספרייט': 'Sprite', 'פאנטה': 'Fanta',
    'שוופס': 'Schweppes', 'נסטלה': 'Nestlé', 'דנונה': 'Danone', 'יופלה': 'Yoplait',
    'מולר': 'Muller', 'אלפרו': 'Alpro', 'ברילה': 'Barilla', 'היינץ': 'Heinz',
    'הלמנס': "Hellmann's", 'קיקומן': 'Kikkoman', 'לואקר': 'Loacker',
    'מילקה': 'Milka', 'אוראו': 'Oreo', 'קינדר': 'Kinder', 'נוטלה': 'Nutella',
    'פררו': 'Ferrero', 'מנטוס': 'Mentos', 'אורביט': 'Orbit', 'בזוקה': 'Bazooka',
    'מאסט': 'Must', 'סניקרס': 'Snickers', 'טוויקס': 'Twix', 'באונטי': 'Bounty',
    'מרס': 'Mars', 'מגנום': 'Magnum', 'לוטוס': 'Lotus', 'טובלרון': 'Toblerone',
    'לינדט': 'Lindt', 'ריטר': 'Ritter', "נייצ'ר ואלי": 'Nature Valley',
    'סטארקיסט': 'StarKist', 'פוסידון': 'Poseidon', 'ויליגר': 'Villiger',
    'סטארבקס': 'Starbucks', 'ניסין': 'Nissin', 'היינקן': 'Heineken',
    'קרלסברג': 'Carlsberg', 'טובורג': 'Tuborg', 'קורונה': 'Corona',
    'סטלה': 'Stella', 'ארטואה': 'Artois', 'גינס': 'Guinness', 'נשר': 'Nesher',
    'בקרדי': 'Bacardi', 'מונסטר': 'Monster', 'בול': 'Bull',
    // household / cosmetics
    'סנו': 'Sano', 'ניקול': 'Nicol', 'לילי': 'Lily', 'פיניש': 'Finish',
    'פיירי': 'Fairy', 'אריאל': 'Ariel', 'פרסיל': 'Persil', 'וניש': 'Vanish',
    'פלמוליב': 'Palmolive', 'קולגייט': 'Colgate', 'ניוואה': 'Nivea',
    'דאב': 'Dove', 'פנטן': 'Pantene', 'האגיס': 'Huggies', 'פמפרס': 'Pampers',
    'טיטולים': 'Titulim', 'קוטקס': 'Kotex', 'אולוויז': 'Always',
    'מקסימה': 'Maxima', 'בדין': 'Badin', 'פינוק': 'Pinuk', 'הוואי': 'Hawaii',
    'קרליין': 'Careline', 'מוריץ': 'Moritz', 'ריצפז': 'Ritzpaz',
    'עוף טוב': 'Of Tov', 'לא ידוע': '', 'לא ידועה': '',  // "unknown" — hide
  };

  // Two-word phrases first: fixed expressions that word-by-word would mangle.
  const PHRASE_MAP = {
    'שיבולת שועל': 'Oats', 'מי עדן': 'Mei Eden', 'מי סודה': 'Soda Water',
    'פסק זמן': 'Pesek Zman', 'עד חצות': 'Ad Chatzot', 'מנה חמה': 'Mana Hama',
    'אבקת כביסה': 'Laundry Powder', 'מרכך כביסה': 'Fabric Softener',
    'משחת שיניים': 'Toothpaste', 'נייר טואלט': 'Toilet Paper',
    'גבינה לבנה': 'White Cheese', 'גבינה צהובה': 'Yellow Cheese',
    'גבינת שמנת': 'Cream Cheese', 'שמנת חמוצה': 'Sour Cream',
    'שמנת מתוקה': 'Sweet Cream', 'שוקולד חלב': 'Milk Chocolate',
    'שוקולד מריר': 'Dark Chocolate', 'שוקולד לבן': 'White Chocolate',
    'שמן זית': 'Olive Oil', 'מיץ תפוזים': 'Orange Juice',
    'תפוחי אדמה': 'Potatoes', 'תפוח אדמה': 'Potato', 'תפו"א': 'Potato',
    'קוקה קולה': 'Coca-Cola', 'רד בול': 'Red Bull', 'טיק טק': 'Tic Tac',
    'יד מרדכי': 'Yad Mordechai', 'טירת צבי': 'Tirat Zvi',
    'בית השיטה': 'Beit HaShita', 'עוף טוב': 'Of Tov', 'רמי לוי': 'Rami Levy',
    'מסיר כתמים': 'Stain Remover', 'נוזל כלים': 'Dish Soap',
    'אל סבון': 'Hand Soap', 'סבון ידיים': 'Hand Soap',
    'תחליב רחצה': 'Body Wash', 'ג\'ל רחצה': 'Shower Gel',
    'חלב מועשר': 'Enriched Milk', 'ביצי חופש': 'Free-Range Eggs',
  };

  const HE_CHARS = {
    'א': 'a', 'ב': 'b', 'ג': 'g', 'ד': 'd', 'ה': 'h', 'ו': 'o', 'ז': 'z',
    'ח': 'ch', 'ט': 't', 'י': 'i', 'כ': 'k', 'ך': 'k', 'ל': 'l',
    'מ': 'm', 'ם': 'm', 'נ': 'n', 'ן': 'n', 'ס': 's', 'ע': 'a',
    'פ': 'p', 'ף': 'f', 'צ': 'tz', 'ץ': 'tz', 'ק': 'k', 'ר': 'r',
    'ש': 'sh', 'ת': 't',
  };

  function translitHe(str) {
    if (!str) return '';
    if (!/[א-ת]/.test(str)) return str; // already Latin
    const words = str.trim().split(/\s+/);
    const mapped = words.map(w => {
      if (BRAND_MAP[w] !== undefined) return BRAND_MAP[w];
      let out = '';
      for (const ch of w) out += (HE_CHARS[ch] ?? (ch.match(/[a-zA-Z0-9%"'.,()\-+×*\/]/) ? ch : ''));
      return out;
    });
    return mapped.join(' ').replace(/\b\w/g, c => c.toUpperCase()).replace(/\s+/g, ' ').trim();
  }

  // Generic product vocabulary — translated. Built from the ~300 most frequent
  // words in the live catalog (all 5 chains, food + household + cosmetics).
  const HE_WORD_EN = {
    // dairy & fridge
    'חלב': 'Milk', 'חמאה': 'Butter', 'חמאת': 'Butter', 'גבינה': 'Cheese',
    'גבינת': 'Cheese', 'קוטג': 'Cottage', "קוטג'": 'Cottage', 'יוגורט': 'Yogurt',
    'שמנת': 'Cream', 'מעדן': 'Dessert', 'ביצים': 'Eggs', 'ביצה': 'Egg',
    'בולגרית': 'Bulgarian', 'צפתית': 'Tzfat', 'פטה': 'Feta', 'גאודה': 'Gouda',
    'מוצרלה': 'Mozzarella', 'ריקוטה': 'Ricotta', 'לאבנה': 'Labaneh',
    'עיזים': 'Goat', 'חלבון': 'Protein', 'לקטוז': 'Lactose', 'ביו': 'Bio',
    // pantry
    'לחם': 'Bread', 'פיתות': 'Pitas', 'פיתה': 'Pita', 'חלה': 'Challah',
    'לחמניות': 'Rolls', 'בצק': 'Dough', 'שמן': 'Oil', 'זית': 'Olive',
    'זיתים': 'Olives', 'קמח': 'Flour', 'סוכר': 'Sugar', 'מלח': 'Salt',
    'קנולה': 'Canola', 'מזוקק': 'Refined', 'חמניות': 'Sunflower',
    'קלוי': 'Roasted', 'מגולענים': 'Pitted', 'מגולען': 'Pitted',
    'אורז': 'Rice', 'פסטה': 'Pasta', 'ספגטי': 'Spaghetti', 'פנה': 'Penne',
    'אטריות': 'Noodles', 'פתיתים': 'Ptitim', 'קוסקוס': 'Couscous',
    'קינואה': 'Quinoa', 'עדשים': 'Lentils', 'חומוס': 'Hummus', 'טחינה': 'Tahini',
    'שעועית': 'Beans', 'אפונה': 'Peas', 'תירס': 'Corn', 'חיטה': 'Wheat',
    'כוסמין': 'Spelt', 'שיפון': 'Rye', 'כוסמת': 'Buckwheat', 'גרנולה': 'Granola',
    'דגנים': 'Cereal', 'דגני': 'Cereal', 'שומשום': 'Sesame', 'קורנפלקס': 'Cornflakes',
    'תערובת': 'Blend', 'אבקת': 'Powder', 'פירורי': 'Crumbs', 'פירורית': 'Breadcrumbs',
    // protein
    'עוף': 'Chicken', 'פרגית': 'Spring Chicken', 'הודו': 'Turkey', 'בשר': 'Meat',
    'בקר': 'Beef', 'טחון': 'Ground', 'חזה': 'Breast', 'כתף': 'Shoulder',
    'שניצל': 'Schnitzel', 'סטייק': 'Steak', 'המבורגר': 'Hamburger',
    'נקניקיות': 'Frankfurters', 'נקניק': 'Sausage', 'פסטרמה': 'Pastrami',
    'סלמי': 'Salami', 'קבנוס': 'Kabanos', 'דג': 'Fish', 'פילה': 'Fillet',
    'טונה': 'Tuna', 'סלמון': 'Salmon', 'הרינג': 'Herring', 'סושי': 'Sushi',
    'מעושן': 'Smoked', 'נתחי': 'Chunks',
    // fruit & veg
    'תפוח': 'Apple', 'בננה': 'Banana', 'תות': 'Strawberry', 'ענבים': 'Grapes',
    'אבטיח': 'Watermelon', 'מנגו': 'Mango', 'אפרסק': 'Peach', 'אננס': 'Pineapple',
    'דובדבן': 'Cherry', 'שרי': 'Cherry', 'אוכמניות': 'Blueberries',
    'קוקוס': 'Coconut', 'לימון': 'Lemon', 'תמר': 'Dates', 'תמרים': 'Dates',
    'עגבניה': 'Tomato', 'עגבניות': 'Tomatoes', 'מלפפון': 'Cucumber',
    'בצל': 'Onion', 'שום': 'Garlic', 'גזר': 'Carrot', 'חסה': 'Lettuce',
    'כרוב': 'Cabbage', 'חציל': 'Eggplant', 'פטריות': 'Mushrooms',
    'ירקות': 'Vegetables', 'פירות': 'Fruits', 'פרי': 'Fruit', 'עלים': 'Leaves',
    'שקדים': 'Almonds', 'שקד': 'Almond', 'בוטנים': 'Peanuts', 'אגוז': 'Nut',
    'אגוזי': 'Nut', 'אגוזים': 'Nuts', 'גרעיני': 'Seeds',
    // snacks & sweets
    'חטיף': 'Snack', 'חטיפי': 'Snack', 'שוקולד': 'Chocolate', 'שוקו': 'Choco',
    'וופל': 'Wafer', 'ביסקוויט': 'Biscuit', 'בייגלה': 'Pretzels',
    'קרקר': 'Cracker', 'פריכיות': 'Rice Cakes', 'ציפס': 'Chips',
    'צ\'יפס': 'Chips', 'סוכריות': 'Candies', 'מסטיק': 'Gum', 'גומי': 'Gummy',
    'מרשמלו': 'Marshmallow', 'עוגת': 'Cake', 'עוגה': 'Cake', 'עוגיות': 'Cookies',
    'קרם': 'Cream', 'מוס': 'Mousse', 'סירופ': 'Syrup', 'דבש': 'Honey',
    'ריבה': 'Jam', 'ממרח': 'Spread', 'וניל': 'Vanilla', 'קראנץ': 'Crunch',
    'במילוי': 'Filled', 'מריר': 'Dark', 'גלידת': 'Ice Cream', 'גלידה': 'Ice Cream',
    'שלגון': 'Ice Pop', 'מקלות': 'Sticks', 'לבבות': 'Hearts',
    // drinks
    'משקה': 'Drink', 'מים': 'Water', 'מי': 'Water', 'קפה': 'Coffee', 'תה': 'Tea',
    'מיץ': 'Juice', 'קולה': 'Cola', 'סודה': 'Soda', 'נקטר': 'Nectar',
    'בירה': 'Beer', 'יין': 'Wine', 'קפסולות': 'Capsules', 'נמס': 'Instant',
    'אספרסו': 'Espresso', 'שחור': 'Black', 'ירוק': 'Green', 'קר': 'Cold',
    'חם': 'Hot', 'פחית': 'Can', 'בקבוק': 'Bottle', 'צנצנת': 'Jar',
    // descriptors
    'טרי': 'Fresh', 'קפוא': 'Frozen', 'עמיד': 'Long-life', 'מפוסטר': 'Pasteurized',
    'יבש': 'Dry', 'קלוי': 'Roasted', 'אפוי': 'Baked', 'מטוגן': 'Fried',
    'שלם': 'Whole', 'מלא': 'Whole', 'דל': 'Low', 'ללא': 'No', 'נטול': 'Free of',
    'שומן': 'Fat', 'מועשר': 'Enriched', 'אורגני': 'Organic', 'אורגנית': 'Organic',
    'פרוס': 'Sliced', 'פרוסות': 'Slices', 'גרוס': 'Grated', 'מגורדת': 'Grated',
    'מיובש': 'Dried', 'מרוכז': 'Concentrated', 'כתית': 'Extra Virgin',
    'מעולה': 'Premium', 'פרימיום': 'Premium', 'קלאסי': 'Classic', 'ביתי': 'Homestyle',
    'טבעי': 'Natural', 'מיוחד': 'Special', 'משפחתי': 'Family', 'קטן': 'Small',
    'גדול': 'Large', 'ענק': 'Giant', 'מיני': 'Mini', 'דק': 'Thin', 'חצי': 'Half',
    'בטעם': 'Flavored', 'טעם': 'Flavor', 'טעמי': 'Flavors', 'מתוק': 'Sweet',
    'חריף': 'Spicy', 'חמוץ': 'Sour', 'קל': 'Light', 'עדין': 'Mild',
    'אדום': 'Red', 'לבן': 'White', 'לבנה': 'White', 'צהוב': 'Yellow',
    'כחול': 'Blue', 'חום': 'Brown', 'ורוד': 'Pink', 'זהב': 'Gold',
    'מוכשר': 'Kosher', 'גלוטן': 'Gluten', 'סויה': 'Soy', 'חלבי': 'Dairy',
    'בסגנון': 'Style', 'בשמן': 'in Oil', 'במשקל': 'by Weight', 'בשקית': 'Bag',
    'שקית': 'Bag', 'שקיות': 'Bags', 'מארז': 'Pack', 'מאגדת': 'Multipack',
    'זוג': 'Pair', 'יחידות': 'pcs', 'יחידה': 'pc', 'יח': 'pcs', "יח'": 'pcs',
    'כוסות': 'Cups', 'צלחות': 'Plates', 'רול': 'Roll', 'סט': 'Set',
    'מיקס': 'Mix', 'סופר': 'Super', 'אקסטרה': 'Extra', 'מקס': 'Max',
    'פרש': 'Fresh', 'פרו': 'Pro', 'בר': 'Bar', 'סטיק': 'Stick', 'בלו': 'Blue',
    'גולד': 'Gold', 'רב': 'Multi', 'דו': 'Dual', 'עם': 'with', 'של': '',
    // household & personal care
    'שמפו': 'Shampoo', 'מרכך': 'Conditioner', 'סבון': 'Soap', 'תחליב': 'Lotion',
    'רחצה': 'Bath', 'לחות': 'Moisture', 'סרום': 'Serum', 'מסכה': 'Mask',
    'מסכת': 'Mask', 'קרמה': 'Crema', 'ג\'ל': 'Gel', 'גל': 'Gel',
    'ספריי': 'Spray', 'תרסיס': 'Spray', 'דאודורנט': 'Deodorant', 'דאו': 'Deo',
    'גילוח': 'Shaving', 'סכיני': 'Razors', 'שיער': 'Hair', 'לשיער': 'for Hair',
    'פנים': 'Face', 'לפנים': 'for Face', 'גוף': 'Body', 'ידיים': 'Hands',
    'עיניים': 'Eyes', 'שפתיים': 'Lips', 'שיניים': 'Teeth', 'משחת': 'Paste',
    'מברשת': 'Brush', 'שפתון': 'Lipstick', 'לק': 'Nail Polish',
    'מסקרה': 'Mascara', 'קונסילר': 'Concealer', 'סומק': 'Blush', 'פודרה': 'Powder',
    'מייקאפ': 'Makeup', 'איפור': 'Makeup', 'גלוס': 'Gloss', 'עפרון': 'Pencil',
    'גוון': 'Shade', 'מאט': 'Matte', 'צבע': 'Color', 'קולור': 'Color',
    'לגבר': "Men's", 'לאישה': "Women's", 'לאשה': "Women's", 'בייבי': 'Baby',
    'כביסה': 'Laundry', 'ניקוי': 'Cleaning', 'לניקוי': 'Cleaner', 'נוזל': 'Liquid',
    'נוזלי': 'Liquid', 'מסיר': 'Remover', 'אקונומיקה': 'Bleach',
    'מגבונים': 'Wipes', 'מטליות': 'Cloths', 'מגבות': 'Towels', 'נייר': 'Paper',
    'ממחטות': 'Tissues', 'תחבושות': 'Pads', 'טמפונים': 'Tampons',
    'חיתולים': 'Diapers', 'מוצצים': 'Pacifiers', 'כפפות': 'Gloves',
    'אשפה': 'Trash', 'אלומיניום': 'Aluminum', 'סוללות': 'Batteries',
    'נר': 'Candle', 'תיק': 'Bag', 'ריח': 'Scent', 'שקוף': 'Clear',
    'קרטין': 'Keratin', 'סיליקון': 'Silicone', 'יום': 'Day', 'לילה': 'Night',
    // misc food
    'רוטב': 'Sauce', 'מרק': 'Soup', 'סלט': 'Salad', 'מחית': 'Puree',
    'מיונז': 'Mayonnaise', 'קטשופ': 'Ketchup', 'חרדל': 'Mustard',
    'חומץ': 'Vinegar', 'תיבול': 'Seasoning', 'פיצה': 'Pizza', 'בורקס': 'Bourekas',
    'שווארמה': 'Shawarma', 'פלאפל': 'Falafel', 'ארוז': 'Packed', 'קוביות': 'Cubes',
    // units
    'ק"ג': 'kg', 'קג': 'kg', 'גרם': 'g', 'גר': 'g', "גר'": 'g',
    'מ"ל': 'ml', 'מל': 'ml', 'ליטר': 'L', 'ס"מ': 'cm',
  };

  // Brands whose Hebrew form is 2+ words ("בן אנד ג'ריס") can't be matched by
  // the word-window below — substitute them on the whole string first.
  const LONG_BRANDS = Object.entries(BRAND_MAP).filter(([he]) => he.includes(' '));

  function replaceLongBrands(str) {
    for (const [he, en] of LONG_BRANDS) {
      if (str.includes(he)) str = str.split(he).join(en);
    }
    return str;
  }

  function translateProductName(str) {
    if (!str) return '';
    if (!/[א-ת]/.test(str)) return str; // already Latin
    str = replaceLongBrands(str);
    if (!/[א-ת]/.test(str)) return str;
    const words = str.trim().split(/\s+/);
    const out = [];
    for (let i = 0; i < words.length; i++) {
      const two = i + 1 < words.length ? words[i] + ' ' + words[i + 1] : null;
      if (two && PHRASE_MAP[two] !== undefined) { out.push(PHRASE_MAP[two]); i++; continue; }
      // Strip punctuation and invisible RTL marks (U+200E/200F in gov data)
      // from the edges so dictionary lookups match.
      const w = words[i], clean = w.replace(/^[^\dA-Za-zא-ת']+|[^\dA-Za-zא-ת']+$/g, '');
      if (BRAND_MAP[clean] !== undefined) { out.push(BRAND_MAP[clean]); continue; }
      out.push(HE_WORD_EN[clean] ?? translitHe(w));
    }
    return out.join(' ').replace(/\s+/g, ' ').trim();
  }

  // ── Promo descriptions ────────────────────────────────────────────────────
  // Deal texts are formulaic ("2 ב- 20.00", "מוצרי טרה ב-5% הנחה", "1+1"), so a
  // pattern pass converts the structure and the word pipeline above handles the
  // product words that remain.
  const PROMO_PATTERNS = [
    [/(\d+)\s*(?:יח'?|יחידות)\s*ב\s*-?\s*(\d+(?:\.\d+)?)/g, '$1 for ₪$2'],
    [/(\d+)\s*ב\s*-?\s*(\d+(?:\.\d+)?)/g, '$1 for ₪$2'],
    [/ב\s*-\s*(\d+(?:\.\d+)?)\s*(?:ש"?ח|₪)/g, 'for ₪$1'],
    [/(\d+(?:\.\d+)?)\s*ש"?ח\s*הנחה/g, '₪$1 off'],
    [/(\d+(?:\.\d+)?)\s*%\s*הנחה/g, '$1% off'],
    [/הנחה\s*(\d+(?:\.\d+)?)\s*%/g, '$1% off'],
    [/השניי?ה?\s*ב\s*-?\s*(\d+(?:\.\d+)?)\s*%/g, '2nd at $1%'],
    [/השניי?ה?\s*ב\s*-?\s*(\d+(?:\.\d+)?)/g, '2nd for ₪$1'],
    [/חצי\s*מחיר/g, 'half price'],
    [/(^|\s)ב-?(\d+(?:\.\d+)?)/g, '$1for ₪$2'],
    [/(\d+)\s*\+\s*(\d+)\s*מתנה/g, '$1+$2 free'],
    [/מתנה/g, 'free'], [/חינם/g, 'free'],
    [/לחברי\s*מועדון/g, 'club members'], [/מועדון/g, 'club'],
    [/מוצרי/g, 'all'], [/הנחה/g, 'off'], [/מבצע/g, 'deal'],
    [/בקניית/g, 'when buying'], [/בקניה\s*מעל/g, 'on orders over'],
    [/ש"?ח/g, '₪'], [/יחידות/g, 'units'], [/יח'?/g, 'pcs'],
  ];

  function translatePromo(str) {
    if (!str) return '';
    if (!/[א-ת]/.test(str)) return str;
    let s = replaceLongBrands(str);
    for (const [re, sub] of PROMO_PATTERNS) s = s.replace(re, sub);
    // whatever Hebrew remains is product/brand words — reuse the name pipeline
    return s.split(/\s+/)
            .map(w => (/[א-ת]/.test(w) ? translateProductName(w) : w))
            .join(' ').replace(/\s+/g, ' ').trim();
  }

  window.ZP = Object.assign(window.ZP || {},
    { translitHe, translateProductName, translatePromo, BRAND_MAP });
})();
