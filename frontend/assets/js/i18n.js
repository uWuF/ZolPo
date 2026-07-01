// UI string catalog. Adding a language = add one block with the same keys and
// list it in LANG_CYCLE. (Product *names* are translated separately — see
// translit.js for the fallback and the backend `item_name_en` column for real
// English. That is where the "bad English" gets fixed over time.)
//
// Exposes: window.ZP.I18N, window.ZP.LANG_CYCLE, window.ZP.LANG_LABELS
(function () {
  const I18N = {
    en: {
      subtitle:          'Tel Aviv · live prices',
      switchLang:        'Switch language',
      searchPlaceholder: 'Search products, brand, or barcode…',
      loading:           'Loading…',
      noResults:         'No products found.',
      add:               'Add',
      item:              'item',
      items:             'items',
      inBasket:          'in basket',
      clear:             'Clear',
      save:              'Save',
      byChoosing:        'by choosing',
      enriching:         'Loading English names…',
      updated:           'Prices updated',
      markets:           'Markets',
      chooseMarkets:     'Choose markets to compare',
      foodMarkets:       'Supermarkets',
      allMarkets:        'All',
      comparable:        'comparable products across selected chains',
    },
    he: {
      subtitle:          'תל אביב · מחירים חיים',
      switchLang:        'החלף שפה',
      searchPlaceholder: 'חיפוש מוצר, מותג או ברקוד…',
      loading:           '…טוען',
      noResults:         '.לא נמצאו מוצרים',
      add:               'הוסף',
      item:              'פריט',
      items:             'פריטים',
      inBasket:          'בסל',
      clear:             'נקה',
      save:              'חיסכון',
      byChoosing:        'ב-',
      enriching:         '…טוען שמות באנגלית',
      updated:           'המחירים עודכנו',
      markets:           'חנויות',
      chooseMarkets:     'בחר חנויות להשוואה',
      foodMarkets:       'סופרמרקטים',
      allMarkets:        'הכל',
      comparable:        'מוצרים להשוואה בין הרשתות שנבחרו',
    },
  };

  const LANG_CYCLE = ['en', 'he'];
  const LANG_LABELS = { en: 'EN', he: 'עב' };

  window.ZP = Object.assign(window.ZP || {}, { I18N, LANG_CYCLE, LANG_LABELS });
})();
