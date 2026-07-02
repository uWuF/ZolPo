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
      reset:             'Reset',
      comparable:        'comparable products across selected chains',
      deals:             'Deals',
      promoUntil:        'until',
      dealsAll:          'All deals',
      kind_one_plus_one: '1+1 / Gift',
      kind_x_for_y:      'Multi-buy',
      kind_percent_off:  '% Off',
      kind_fixed_price:  'Special price',
      kind_club:         'Club',
      kind_other:        'Other',
      moreDeals:         'more',
      dealsAt:           'Deals at',
      minQty:            'min',
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
      reset:             'איפוס',
      comparable:        'מוצרים להשוואה בין הרשתות שנבחרו',
      deals:             'מבצעים',
      promoUntil:        'עד',
      dealsAll:          'כל המבצעים',
      kind_one_plus_one: '1+1 / מתנה',
      kind_x_for_y:      'כמה ב…',
      kind_percent_off:  '% הנחה',
      kind_fixed_price:  'מחיר מיוחד',
      kind_club:         'מועדון',
      kind_other:        'אחר',
      moreDeals:         'נוספים',
      dealsAt:           'מבצעים ב',
      minQty:            'מינ׳',
    },
  };

  const LANG_CYCLE = ['en', 'he'];
  const LANG_LABELS = { en: 'EN', he: 'עב' };

  window.ZP = Object.assign(window.ZP || {}, { I18N, LANG_CYCLE, LANG_LABELS });
})();
