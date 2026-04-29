import { useState, useEffect } from 'react';

// ==================== TYPES ====================
interface Product {
  id: number;
  name: string;
  description: string;
  price: number;
  category: string;
  emoji: string;
  image_url?: string;
  photos?: string[];   // Массив фото (карусель)
  stock: number;
}

interface CartItem {
  product: Product;
  quantity: number;
}

interface OrderFormData {
  name: string;
  phone: string;
  address: string;
  comment: string;
}

interface Order {
  id: number;
  status: string;
  total: number;
  date: string;
  items: { name: string; qty: number; price: number }[];
}

type ViewType = 'catalog' | 'cart' | 'checkout' | 'success' | 'profile';
type SortType = 'default' | 'price_asc' | 'price_desc';

// ==================== TELEGRAM WEBAPP TYPES ====================
declare global {
  interface Window {
    Telegram?: {
      WebApp: {
        ready: () => void;
        close: () => void;
        sendData: (data: string) => void;
        expand: () => void;
        initData?: string;
        initDataUnsafe?: {
          user?: {
            id: number;
            first_name: string;
            last_name?: string;
            username?: string;
          };
        };
        colorScheme: 'light' | 'dark';
        setHeaderColor: (color: string) => void;
        setBackgroundColor: (color: string) => void;
        HapticFeedback: {
          impactOccurred: (style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft') => void;
          notificationOccurred: (type: 'error' | 'success' | 'warning') => void;
        };
      };
    };
  }
}

// ==================== ЗАПАСНЫЕ ДАННЫЕ ====================
const MOCK_PRODUCTS: Product[] = [
  { id: 1, name: 'Диван «Комфорт»', description: 'Мягкий трёхместный диван с велюровой обивкой.', price: 45000, category: 'Диваны', emoji: '🛋️', stock: 10, photos: [] },
  { id: 4, name: 'Кровать «Сон»', description: 'Двуспальная кровать 160×200 с подъёмным механизмом.', price: 35000, category: 'Кровати', emoji: '🛏️', stock: 5, photos: [] },
  { id: 7, name: 'Шкаф-купе «Гардероб»', description: 'Трёхдверный шкаф-купе с зеркалом.', price: 54000, category: 'Шкафы', emoji: '🗄️', stock: 3, photos: [] },
  { id: 9, name: 'Стол обеденный «Дуб»', description: 'Раскладной стол из массива дуба.', price: 38000, category: 'Столы', emoji: '🪵', stock: 9, photos: [] },
  { id: 11, name: 'Стул «Элегант»', description: 'Обеденный стул с мягким сиденьем.', price: 8500, category: 'Стулья', emoji: '💺', stock: 20, photos: [] },
  { id: 14, name: 'Кухня «Стандарт»', description: 'Кухонный гарнитур 2.4 м.', price: 95000, category: 'Кухни', emoji: '🍳', stock: 2, photos: [] },
];

// ==================== HELPERS ====================
const getCategoryGradient = (category: string): string => {
  const map: Record<string, string> = {
    'Диваны': 'grad-sofas',
    'Кровати': 'grad-beds',
    'Шкафы': 'grad-wardrobes',
    'Столы': 'grad-tables',
    'Стулья': 'grad-chairs',
    'Кухни': 'grad-kitchens',
  };
  return map[category] || 'grad-default';
};

// ==================== PHOTO CAROUSEL ====================
function PhotoCarousel({ photos, emoji, category }: { photos: string[]; emoji: string; category: string }) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [failedImages, setFailedImages] = useState<Set<number>>(new Set());

  if (!photos || photos.length === 0) {
    return (
      <div className={`${getCategoryGradient(category)} h-52 flex items-center justify-center`}>
        <span className="text-7xl drop-shadow-lg">{emoji}</span>
      </div>
    );
  }

  const goTo = (index: number) => {
    if (index < 0) setCurrentIndex(photos.length - 1);
    else if (index >= photos.length) setCurrentIndex(0);
    else setCurrentIndex(index);
  };

  return (
    <div className="relative h-52 bg-gray-100 overflow-hidden">
      {/* Рендерим ВСЕ фото сразу — браузер их предзагрузит */}
      {photos.map((url, idx) => (
        <img
          key={`photo-${idx}-${url}`}
          src={url}
          className={`absolute inset-0 w-full h-full object-cover transition-opacity duration-300 ${
            idx === currentIndex ? 'opacity-100 z-10' : 'opacity-0 z-0'
          }`}
          alt=""
          onError={() => setFailedImages(prev => new Set(prev).add(idx))}
          loading="eager"
        />
      ))}

      {/* Заглушка если текущее фото не загрузилось */}
      {failedImages.has(currentIndex) && (
        <div className={`absolute inset-0 z-10 ${getCategoryGradient(category)} flex items-center justify-center`}>
          <span className="text-7xl drop-shadow-lg">{emoji}</span>
        </div>
      )}

      {/* Кнопки ‹ › — только если больше 1 фото */}
      {photos.length > 1 && (
        <>
          <button
            onClick={(e) => { e.stopPropagation(); goTo(currentIndex - 1); }}
            className="absolute left-2 top-1/2 -translate-y-1/2 w-8 h-8 bg-black/30 backdrop-blur-sm rounded-full text-white flex items-center justify-center text-lg hover:bg-black/50 transition-colors z-20"
          >
            ‹
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); goTo(currentIndex + 1); }}
            className="absolute right-2 top-1/2 -translate-y-1/2 w-8 h-8 bg-black/30 backdrop-blur-sm rounded-full text-white flex items-center justify-center text-lg hover:bg-black/50 transition-colors z-20"
          >
            ›
          </button>
          {/* Точки */}
          <div className="absolute bottom-2 left-1/2 -translate-x-1/2 flex gap-1.5 z-20">
            {photos.map((_, idx) => (
              <button
                key={idx}
                onClick={(e) => { e.stopPropagation(); setCurrentIndex(idx); }}
                className={`carousel-dot ${idx === currentIndex ? 'active' : ''}`}
              />
            ))}
          </div>
          {/* Счётчик */}
          <div className="absolute top-2 right-2 bg-black/30 backdrop-blur-sm text-white text-[10px] font-medium px-2 py-0.5 rounded-full z-20">
            {currentIndex + 1}/{photos.length}
          </div>
        </>
      )}
    </div>
  );
}

// ==================== HEADER ====================
function Header({
  cartCount,
  onCartClick,
  onBack,
  showBack,
  title,
  onProfile
}: {
  cartCount: number;
  onCartClick: () => void;
  onBack?: () => void;
  showBack: boolean;
  title: string;
  onProfile: () => void;
}) {
  const tgUser = window.Telegram?.WebApp?.initDataUnsafe?.user;
  const initials = tgUser ? (tgUser.first_name[0] + (tgUser.last_name ? tgUser.last_name[0] : '')) : '👤';

  return (
    <header className="sticky top-0 z-30 bg-white/90 backdrop-blur-lg border-b border-brand-100 shadow-sm">
      <div className="flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-3">
          {showBack && onBack ? (
            <button onClick={onBack} className="p-1.5 -ml-1.5 rounded-xl hover:bg-brand-100 transition-colors">
              <svg className="w-6 h-6 text-brand-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
            </button>
          ) : (
            <button onClick={onProfile} className="text-xs font-bold text-brand-700 bg-brand-100 px-3 py-1.5 rounded-full flex items-center gap-2 hover:bg-brand-200 transition-colors active:scale-95">
              <div className="w-5 h-5 bg-brand-600 text-white rounded-full flex items-center justify-center text-[10px]">
                {initials}
              </div>
              <span>Кабинет</span>
            </button>
          )}
          <div>
            <h1 className="text-lg font-bold text-brand-800 leading-tight">{title}</h1>
          </div>
        </div>
        {!showBack && (
          <button
            onClick={onCartClick}
            className="relative p-2.5 rounded-2xl bg-brand-100 hover:bg-brand-200 transition-colors"
          >
            <svg className="w-6 h-6 text-brand-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 100 4 2 2 0 000-4z" />
            </svg>
            {cartCount > 0 && (
              <span className="pulse-badge absolute -top-1 -right-1 bg-red-500 text-white text-xs font-bold rounded-full w-5 h-5 flex items-center justify-center">
                {cartCount}
              </span>
            )}
          </button>
        )}
      </div>
    </header>
  );
}

// ==================== PRODUCT CARD ====================
function ProductCard({
  product,
  cartQuantity,
  onAdd,
  onRemove,
  onDetail
}: {
  product: Product;
  cartQuantity: number;
  onAdd: () => void;
  onRemove: () => void;
  onDetail: () => void;
}) {
  const [thumbError, setThumbError] = useState(false);
  const hasPhotos = product.photos && product.photos.length > 0;
  const hasImage = !!product.image_url;
  const thumbSrc = hasPhotos ? product.photos![0] : (hasImage ? product.image_url : null);
  const showThumb = thumbSrc && !thumbError;

  return (
    <div className="product-card bg-white rounded-3xl shadow-sm border border-brand-100/60 overflow-hidden flex flex-col h-full">
      <div
        onClick={onDetail}
        className={`${!showThumb ? getCategoryGradient(product.category) : 'bg-gray-100'} h-36 flex items-center justify-center cursor-pointer relative overflow-hidden`}
      >
        {showThumb ? (
          <img src={thumbSrc} className="w-full h-full object-cover" loading="lazy" alt={product.name} onError={() => setThumbError(true)} />
        ) : (
          <span className="text-5xl drop-shadow-lg">{product.emoji}</span>
        )}

        {/* Бейдж "Нет в наличии" */}
        {product.stock === 0 && (
          <div className="absolute inset-0 bg-white/60 backdrop-blur-[2px] flex items-center justify-center z-10">
            <span className="bg-gray-800 text-white text-[10px] font-bold px-2 py-1 rounded-full">Нет в наличии</span>
          </div>
        )}
        {/* Бейдж малого остатка */}
        {product.stock > 0 && product.stock < 5 && (
          <div className="absolute top-2 right-2 bg-red-500 text-white text-[10px] font-bold px-2 py-0.5 rounded-full z-10">
            Ост: {product.stock}
          </div>
        )}
        {/* Бейдж нескольких фото */}
        {hasPhotos && product.photos!.length > 1 && (
          <div className="absolute top-2 left-2 bg-black/30 backdrop-blur-sm text-white text-[10px] font-medium px-1.5 py-0.5 rounded-full z-10">
            📷 {product.photos!.length}
          </div>
        )}

        <div className="absolute bottom-2 left-2 bg-black/20 backdrop-blur-sm text-white text-[10px] font-medium px-2.5 py-1 rounded-full">
          {product.category}
        </div>
      </div>

      <div className="p-3.5 flex flex-col flex-1">
        <h3
          onClick={onDetail}
          className="text-sm font-bold text-brand-800 leading-snug cursor-pointer line-clamp-2 min-h-[2.5rem] mb-auto"
        >
          {product.name}
        </h3>
        <div className="flex items-center justify-between mt-2.5">
          <span className="text-base font-extrabold text-brand-700">
            {product.price.toLocaleString()} ₽
          </span>
          {product.stock > 0 ? (
            cartQuantity === 0 ? (
              <button
                onClick={onAdd}
                className="bg-brand-600 hover:bg-brand-700 text-white text-xs font-bold px-4 py-2 rounded-xl transition-colors active:scale-95"
              >
                В корзину
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <button onClick={onRemove} className="w-8 h-8 rounded-xl bg-brand-100 hover:bg-brand-200 flex items-center justify-center text-brand-700 font-bold">−</button>
                <span className="text-sm font-bold text-brand-800 w-4 text-center">{cartQuantity}</span>
                <button onClick={onAdd} className="w-8 h-8 rounded-xl bg-brand-600 hover:bg-brand-700 flex items-center justify-center text-white font-bold">+</button>
              </div>
            )
          ) : (
            <span className="text-xs text-gray-400">Нет</span>
          )}
        </div>
      </div>
    </div>
  );
}

// ==================== CHECKOUT FORM ====================
function CheckoutForm({
  cart,
  onBack,
  onSubmit
}: {
  cart: CartItem[];
  onBack: () => void;
  onSubmit: (data: OrderFormData) => void;
}) {
  const [form, setForm] = useState<OrderFormData>({ name: '', phone: '', address: '', comment: '' });
  const [errors, setErrors] = useState<Record<string, boolean>>({});

  const total = cart.reduce((sum, item) => sum + item.product.price * item.quantity, 0);

  useEffect(() => {
    const tgUser = window.Telegram?.WebApp?.initDataUnsafe?.user;
    if (tgUser) {
      setForm(prev => ({
        ...prev,
        name: prev.name || [tgUser.first_name, tgUser.last_name].filter(Boolean).join(' '),
      }));
    }
  }, []);

  const handleSubmit = () => {
    const newErrors: Record<string, boolean> = {};
    if (form.name.trim().length < 2) newErrors.name = true;
    if (form.phone.trim().length < 10) newErrors.phone = true;
    if (form.address.trim().length < 5) newErrors.address = true;
    setErrors(newErrors);

    if (Object.keys(newErrors).length > 0) {
      if (window.Telegram?.WebApp?.HapticFeedback) window.Telegram.WebApp.HapticFeedback.notificationOccurred('error');
      return;
    }
    onSubmit(form);
  };

  const inputClass = (field: string) =>
    `w-full px-4 py-3 rounded-2xl border-2 text-sm font-medium transition-colors outline-none ${
      errors[field]
        ? 'border-red-400 bg-red-50 text-red-800'
        : 'border-brand-200 bg-white text-brand-800 focus:border-brand-500'
    }`;

  return (
    <div className="min-h-screen bg-brand-50">
      <Header cartCount={0} onCartClick={() => {}} onBack={onBack} showBack={true} title="Оформление" onProfile={() => {}} />
      <div className="p-4 space-y-4 slide-up pb-24">
        {/* Сумма */}
        <div className="bg-white rounded-2xl p-4 border border-brand-100 shadow-sm">
          <div className="text-xs text-brand-400 uppercase font-bold mb-1">Сумма к оплате</div>
          <div className="text-2xl font-extrabold text-brand-800">{total.toLocaleString()} ₽</div>
        </div>

        {/* Товары в заказе */}
        <div className="bg-white rounded-2xl p-4 border border-brand-100 shadow-sm">
          <h3 className="text-sm font-bold text-brand-800 mb-3">Товары ({cart.length})</h3>
          <div className="space-y-2">
            {cart.map(item => (
              <div key={item.product.id} className="flex justify-between text-sm">
                <span className="text-brand-600">{item.product.name} <span className="text-brand-400">×{item.quantity}</span></span>
                <span className="font-semibold text-brand-800">{(item.product.price * item.quantity).toLocaleString()} ₽</span>
              </div>
            ))}
          </div>
        </div>

        {/* Форма */}
        <div className="bg-white rounded-2xl p-4 border border-brand-100 shadow-sm space-y-3">
          <h3 className="text-sm font-bold text-brand-800 mb-1">Данные для доставки</h3>
          <div>
            <label className="block text-xs font-semibold text-brand-500 mb-1.5 ml-1">ФИО *</label>
            <input
              className={inputClass('name')}
              placeholder="Иванов Иван Иванович"
              value={form.name}
              onChange={e => { setForm({ ...form, name: e.target.value }); setErrors({ ...errors, name: false }); }}
            />
            {errors.name && <p className="text-xs text-red-500 mt-1 ml-1">Введите минимум 2 символа</p>}
          </div>
          <div>
            <label className="block text-xs font-semibold text-brand-500 mb-1.5 ml-1">Телефон *</label>
            <input
              className={inputClass('phone')}
              placeholder="+79001234567"
              type="tel"
              value={form.phone}
              onChange={e => { setForm({ ...form, phone: e.target.value }); setErrors({ ...errors, phone: false }); }}
            />
            {errors.phone && <p className="text-xs text-red-500 mt-1 ml-1">Введите корректный номер телефона</p>}
          </div>
          <div>
            <label className="block text-xs font-semibold text-brand-500 mb-1.5 ml-1">Адрес доставки *</label>
            <textarea
              className={inputClass('address')}
              placeholder="г. Москва, ул. Примерная, д. 1, кв. 10"
              rows={2}
              value={form.address}
              onChange={e => { setForm({ ...form, address: e.target.value }); setErrors({ ...errors, address: false }); }}
            />
            {errors.address && <p className="text-xs text-red-500 mt-1 ml-1">Введите полный адрес (мин. 5 символов)</p>}
          </div>
          <div>
            <label className="block text-xs font-semibold text-brand-500 mb-1.5 ml-1">Комментарий</label>
            <input
              className={inputClass('comment')}
              placeholder="Код домофона, этаж..."
              value={form.comment}
              onChange={e => setForm({ ...form, comment: e.target.value })}
            />
          </div>
        </div>
      </div>
      {/* Кнопка подтверждения */}
      <div className="fixed bottom-0 left-0 right-0 p-4 bg-white/80 backdrop-blur-lg border-t border-brand-100">
        <button
          onClick={handleSubmit}
          className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-4 rounded-2xl shadow-lg shadow-emerald-200/50 active:scale-[0.98] transition-transform"
        >
          ✅ Подтвердить заказ — {total.toLocaleString()} ₽
        </button>
      </div>
    </div>
  );
}

// ==================== PROFILE ====================
function Profile({ onBack }: { onBack: () => void }) {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [userInfo, setUserInfo] = useState<{ first_name: string; last_name: string; username: string } | null>(null);

  // Пытаемся взять данные из initDataUnsafe (иногда пусто)
  const tgUser = window.Telegram?.WebApp?.initDataUnsafe?.user;
  // initData — подписанная строка, есть всегда когда Mini App открыт из Telegram
  const initData = window.Telegram?.WebApp?.initData || '';

  const displayUser = userInfo || tgUser;
  const firstName = displayUser?.first_name || 'Гость';
  const lastName = displayUser?.last_name || '';
  const username = displayUser?.username ? `@${displayUser.username}` : '';
  const initials = firstName.charAt(0) + (lastName ? lastName.charAt(0) : '');

  useEffect(() => {
    // Стратегия: если initDataUnsafe.user есть — используем старый GET
    // Если нет — отправляем initData на сервер для парсинга
    const userId = tgUser?.id;
    if (userId) {
      // Старый путь — данные уже есть на клиенте
      fetch(`/api/my-orders?user_id=${userId}`, { headers: { 'Bypass-Tunnel-Reminder': 'true' } })
        .then(res => res.json())
        .then(data => { setOrders(data); setLoading(false); })
        .catch(() => setLoading(false));
    } else if (initData) {
      // Новый путь — парсим initData на сервере
      fetch('/api/user-info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Bypass-Tunnel-Reminder': 'true' },
        body: JSON.stringify({ initData }),
      })
        .then(res => res.json())
        .then(data => {
          if (data.user) setUserInfo(data.user);
          if (data.orders) setOrders(data.orders);
          setLoading(false);
        })
        .catch(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const totalSpent = orders.reduce((sum, o) => sum + o.total, 0);
  const isGuest = !displayUser;

  const getStatusIcon = (status: string) => {
    const map: Record<string, string> = {
      'Новый': '🆕', 'Оплачено': '💰', 'В обработке': '⚙️',
      'Готов к отгрузке': '📦', 'Отгружен': '🚛', 'Отменён': '❌'
    };
    return map[status] || '❓';
  };

  return (
    <div className="min-h-screen bg-brand-50 pb-10">
      <Header cartCount={0} onCartClick={() => {}} onBack={onBack} showBack={true} title="Личный кабинет" onProfile={() => {}} />
      
      {/* User Info Card */}
      <div className="px-4 mt-4 slide-up">
        <div className="bg-white rounded-3xl p-5 shadow-sm border border-brand-100 flex items-center gap-4 relative overflow-hidden">
          {/* Abstract background blobs */}
          <div className="absolute -top-10 -right-10 w-32 h-32 bg-brand-100 rounded-full blur-3xl opacity-50"></div>
          <div className="absolute -bottom-10 -left-10 w-32 h-32 bg-emerald-100 rounded-full blur-3xl opacity-50"></div>
          
          <div className="relative z-10 min-w-[4rem] w-16 h-16 bg-gradient-to-br from-brand-500 to-brand-700 text-white rounded-full flex items-center justify-center text-2xl font-bold shadow-lg shadow-brand-200">
            {initials || '👤'}
          </div>
          <div className="relative z-10">
            <h2 className="text-xl font-bold text-brand-800 leading-tight">{firstName} {lastName}</h2>
            {username && <p className="text-sm text-brand-500">{username}</p>}
            {isGuest && !loading && <p className="text-xs text-orange-500 mt-1">Режим предпросмотра (не Telegram)</p>}
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="px-4 mt-4 grid grid-cols-2 gap-3 slide-up" style={{animationDelay: '0.1s'}}>
        <div className="bg-white rounded-2xl p-4 border border-brand-100 shadow-sm flex flex-col justify-center items-center">
          <div className="text-3xl mb-1">🛒</div>
          <div className="text-xl font-extrabold text-brand-800">{orders.length}</div>
          <div className="text-xs font-semibold text-brand-500 uppercase">Всего заказов</div>
        </div>
        <div className="bg-white rounded-2xl p-4 border border-brand-100 shadow-sm flex flex-col justify-center items-center">
          <div className="text-3xl mb-1">💳</div>
          <div className="text-xl font-extrabold text-brand-800">{totalSpent.toLocaleString()} ₽</div>
          <div className="text-xs font-semibold text-brand-500 uppercase">Сумма покупок</div>
        </div>
      </div>

      {/* Orders List */}
      <div className="px-4 mt-6 slide-up" style={{animationDelay: '0.2s'}}>
        <h3 className="text-lg font-bold text-brand-800 mb-3 flex items-center gap-2">
          <span>📦 Мои заказы</span>
        </h3>
        
        {loading ? (
          <div className="text-center py-10">
            <div className="inline-block w-8 h-8 border-3 border-brand-300 border-t-brand-700 rounded-full animate-spin"></div>
          </div>
        ) : orders.length === 0 ? (
          <div className="text-center py-10 bg-white rounded-2xl border border-brand-100">
            <div className="text-4xl mb-2 text-brand-200">📭</div>
            <p className="font-medium text-brand-500">У вас пока нет заказов</p>
            <button onClick={onBack} className="mt-4 text-brand-600 font-bold bg-brand-50 px-4 py-2 rounded-xl border border-brand-100">
              Перейти в каталог
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {orders.map(order => (
              <div key={order.id} className="bg-white p-4 rounded-2xl border border-brand-100 shadow-sm">
                <div className="flex justify-between items-start mb-3">
                  <div>
                    <div className="font-bold text-brand-800">Заказ #{order.id}</div>
                    <div className="text-xs text-brand-400">{order.date}</div>
                  </div>
                  <div className="px-2 py-1 rounded-lg text-[10px] font-bold bg-brand-50 border border-brand-100 text-brand-700 uppercase">
                    {getStatusIcon(order.status)} {order.status}
                  </div>
                </div>
                <div className="space-y-1.5 mb-3">
                  {order.items.map((item, idx) => (
                    <div key={idx} className="flex justify-between text-sm">
                      <span className="text-brand-600 line-clamp-1 pr-2">{item.name} <span className="text-brand-400">×{item.qty}</span></span>
                      <span className="font-medium text-brand-800 whitespace-nowrap">{(item.price * item.qty).toLocaleString()} ₽</span>
                    </div>
                  ))}
                </div>
                <div className="border-t border-brand-100 pt-3 flex justify-between items-center font-bold">
                  <span className="text-brand-500 text-sm">Итого:</span>
                  <span className="text-brand-800 text-base">{order.total.toLocaleString()} ₽</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ==================== MAIN APP ====================
export function App() {
  const [view, setView] = useState<ViewType>('catalog');
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<string[]>(['Все']);
  const [activeCategory, setActiveCategory] = useState('Все');
  const [cart, setCart] = useState<CartItem[]>([]);
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortType, setSortType] = useState<SortType>('default');
  const [showInStockOnly, setShowInStockOnly] = useState(false);

  useEffect(() => {
    if (window.Telegram?.WebApp) {
      window.Telegram.WebApp.ready();
      window.Telegram.WebApp.expand();
      try { window.Telegram.WebApp.setHeaderColor('#ffffff'); } catch (_) {}
    }

    // Загрузка товаров
    fetch('/api/products', { headers: { 'Bypass-Tunnel-Reminder': 'true' } })
      .then(res => {
        if (!res.ok) throw new Error('Server error');
        return res.json();
      })
      .then(data => {
        if (Array.isArray(data) && data.length > 0) {
          setProducts(data);
          const cats = ['Все', ...Array.from(new Set(data.map((p: Product) => p.category))) as string[]];
          setCategories(cats);
        } else {
          setProducts(MOCK_PRODUCTS);
          setCategories(['Все', 'Диваны', 'Кровати', 'Шкафы', 'Столы', 'Стулья', 'Кухни']);
        }
        setLoading(false);
      })
      .catch((e) => {
        console.error('API Error, using MOCK:', e);
        setProducts(MOCK_PRODUCTS);
        setCategories(['Все', 'Диваны', 'Кровати', 'Шкафы', 'Столы', 'Стулья', 'Кухни']);
        setLoading(false);
      });

    // Восстановление корзины
    try {
      const saved = localStorage.getItem('cart');
      if (saved) setCart(JSON.parse(saved));
    } catch (_) {}
  }, []);

  // Сохранение корзины
  useEffect(() => {
    localStorage.setItem('cart', JSON.stringify(cart));
  }, [cart]);

  const addToCart = (product: Product) => {
    const currentQty = cart.find(i => i.product.id === product.id)?.quantity || 0;
    if (currentQty >= product.stock) {
      try { window.Telegram?.WebApp?.HapticFeedback?.notificationOccurred('error'); } catch (_) {}
      return;
    }
    try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred('medium'); } catch (_) {}
    setCart(prev => {
      const existing = prev.find(i => i.product.id === product.id);
      return existing
        ? prev.map(i => i.product.id === product.id ? { ...i, quantity: i.quantity + 1 } : i)
        : [...prev, { product, quantity: 1 }];
    });
  };

  const removeFromCart = (id: number) => {
    try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred('light'); } catch (_) {}
    setCart(prev => {
      const existing = prev.find(i => i.product.id === id);
      return existing && existing.quantity > 1
        ? prev.map(i => i.product.id === id ? { ...i, quantity: i.quantity - 1 } : i)
        : prev.filter(i => i.product.id !== id);
    });
  };

  const handleOrderSubmit = (formData: OrderFormData) => {
    const data = {
      items: cart.map(i => ({ id: i.product.id, name: i.product.name, price: i.product.price, quantity: i.quantity })),
      customer: formData,
      total: cart.reduce((s, i) => s + i.product.price * i.quantity, 0)
    };
    try {
      window.Telegram?.WebApp?.sendData(JSON.stringify(data));
    } catch (_) {
      alert('Заказ отправлен! (тестовый режим)');
    }
  };

  // --- Routing ---
  if (view === 'checkout') return <CheckoutForm cart={cart} onBack={() => setView('catalog')} onSubmit={handleOrderSubmit} />;
  if (view === 'profile') return <Profile onBack={() => setView('catalog')} />;

  // Фильтрация по категории
  let filtered = activeCategory === 'Все' ? products : products.filter(p => p.category === activeCategory);

  // Фильтр "Только в наличии"
  if (showInStockOnly) {
    filtered = filtered.filter(p => p.stock > 0);
  }

  // Поиск по названию и описанию
  if (searchQuery.trim()) {
    const q = searchQuery.toLowerCase().trim();
    filtered = filtered.filter(p =>
      p.name.toLowerCase().includes(q) ||
      p.description.toLowerCase().includes(q)
    );
  }

  // Сортировка по цене
  if (sortType === 'price_asc') {
    filtered = [...filtered].sort((a, b) => a.price - b.price);
  } else if (sortType === 'price_desc') {
    filtered = [...filtered].sort((a, b) => b.price - a.price);
  }

  const cartTotal = cart.reduce((sum, item) => sum + item.quantity, 0);

  return (
    <div className="min-h-screen bg-brand-50 pb-20">
      <Header
        cartCount={cartTotal}
        onCartClick={() => setView('checkout')}
        showBack={false}
        title="Каталог"
        onProfile={() => setView('profile')}
      />

      {/* Поиск */}
      <div className="sticky top-[57px] z-20 bg-brand-50/95 backdrop-blur-sm border-b border-brand-100/50">
        <div className="px-4 pt-3">
          <div className="relative">
            <svg className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4.5 h-4.5 text-brand-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              placeholder="Поиск по каталогу..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2.5 rounded-2xl border border-brand-200 bg-white text-sm text-brand-800 placeholder-brand-400 outline-none focus:border-brand-500 transition-colors"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-brand-400 hover:text-brand-600 text-lg"
              >
                ✕
              </button>
            )}
          </div>
        </div>

        {/* Категории */}
        <div className="flex gap-2 px-4 py-2.5 overflow-x-auto hide-scrollbar">
          {categories.map(cat => (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              className={`flex-shrink-0 px-4 py-2 rounded-2xl text-sm font-semibold transition-all duration-200 ${
                activeCategory === cat
                  ? 'bg-brand-700 text-white shadow-md'
                  : 'bg-white text-brand-600 border border-brand-200'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Сортировка и фильтры */}
        <div className="flex gap-2 px-4 pb-2.5 flex-wrap">
          <button
            onClick={() => setSortType(sortType === 'price_asc' ? 'default' : 'price_asc')}
            className={`text-xs font-semibold px-3 py-1.5 rounded-xl transition-all ${
              sortType === 'price_asc'
                ? 'bg-brand-700 text-white'
                : 'bg-white text-brand-500 border border-brand-200'
            }`}
          >
            Цена ↑
          </button>
          <button
            onClick={() => setSortType(sortType === 'price_desc' ? 'default' : 'price_desc')}
            className={`text-xs font-semibold px-3 py-1.5 rounded-xl transition-all ${
              sortType === 'price_desc'
                ? 'bg-brand-700 text-white'
                : 'bg-white text-brand-500 border border-brand-200'
            }`}
          >
            Цена ↓
          </button>
          <button
            onClick={() => setShowInStockOnly(!showInStockOnly)}
            className={`text-xs font-semibold px-3 py-1.5 rounded-xl transition-all ${
              showInStockOnly
                ? 'bg-emerald-600 text-white'
                : 'bg-white text-brand-500 border border-brand-200'
            }`}
          >
            ✅ В наличии
          </button>
          {(searchQuery || sortType !== 'default' || showInStockOnly) && (
            <button
              onClick={() => { setSearchQuery(''); setSortType('default'); setShowInStockOnly(false); }}
              className="text-xs font-semibold px-3 py-1.5 rounded-xl bg-red-50 text-red-500 border border-red-200"
            >
              ✕ Сброс
            </button>
          )}
          <span className="text-xs text-brand-400 self-center ml-auto">
            {filtered.length} шт.
          </span>
        </div>
      </div>

      {/* Товары */}
      <div className="px-3 pt-4">
        {loading ? (
          <div className="text-center py-16">
            <div className="inline-block w-10 h-10 border-3 border-brand-300 border-t-brand-700 rounded-full animate-spin"></div>
            <p className="text-brand-400 mt-4 font-medium">Загрузка каталога...</p>
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-10 text-brand-400">
            <div className="text-4xl mb-3">🔍</div>
            {searchQuery ? (
              <>
                <p className="font-medium">Ничего не найдено</p>
                <p className="text-sm mt-1">По запросу «{searchQuery}»</p>
                <button
                  onClick={() => setSearchQuery('')}
                  className="mt-3 text-sm text-brand-600 underline"
                >
                  Сбросить поиск
                </button>
              </>
            ) : (
              <p>Нет товаров в этой категории</p>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {filtered.map(p => (
              <ProductCard
                key={p.id}
                product={p}
                cartQuantity={cart.find(i => i.product.id === p.id)?.quantity || 0}
                onAdd={() => addToCart(p)}
                onRemove={() => removeFromCart(p.id)}
                onDetail={() => setSelectedProduct(p)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Плавающая корзина */}
      {cart.length > 0 && (
        <div className="fixed bottom-4 left-4 right-4 z-30 slide-up">
          <button
            onClick={() => setView('checkout')}
            className="w-full bg-brand-700 hover:bg-brand-800 text-white font-bold py-4 rounded-2xl shadow-2xl flex items-center justify-center gap-3 active:scale-[0.98] transition-transform"
          >
            <span>🛒 Корзина</span>
            <span className="bg-white/20 px-3 py-0.5 rounded-full text-sm">
              {cartTotal} шт — {cart.reduce((s, i) => s + i.product.price * i.quantity, 0).toLocaleString()} ₽
            </span>
          </button>
        </div>
      )}

      {/* Модалка товара с каруселью */}
      {selectedProduct && (
        <div
          className="fixed inset-0 z-50 bg-black/50 flex items-end sm:items-center justify-center"
          onClick={() => setSelectedProduct(null)}
        >
          <div
            className="slide-up bg-white w-full sm:max-w-md sm:rounded-3xl rounded-t-3xl max-h-[90vh] overflow-y-auto"
            onClick={e => e.stopPropagation()}
          >
            {/* Карусель фотографий */}
            <div className="relative">
              <PhotoCarousel
                photos={selectedProduct.photos || (selectedProduct.image_url ? [selectedProduct.image_url] : [])}
                emoji={selectedProduct.emoji}
                category={selectedProduct.category}
              />
              <button
                onClick={() => setSelectedProduct(null)}
                className="absolute top-4 right-4 w-9 h-9 bg-black/20 backdrop-blur-sm rounded-full text-white flex items-center justify-center z-20"
              >
                ✕
              </button>
            </div>

            <div className="p-5">
              <h2 className="text-xl font-bold text-brand-800 mb-1">{selectedProduct.name}</h2>
              <div className="text-xs text-brand-400 mb-3">{selectedProduct.category}</div>
              <p className="text-sm text-brand-500 mb-4 leading-relaxed">{selectedProduct.description}</p>

              {/* Остаток */}
              <div className="mb-4">
                {selectedProduct.stock > 0 ? (
                  <span className="text-xs font-medium text-emerald-600 bg-emerald-50 px-2 py-1 rounded-full">
                    ✅ В наличии: {selectedProduct.stock} шт.
                  </span>
                ) : (
                  <span className="text-xs font-medium text-red-600 bg-red-50 px-2 py-1 rounded-full">
                    ❌ Нет в наличии
                  </span>
                )}
              </div>

              <div className="flex justify-between items-center">
                <span className="text-2xl font-extrabold text-brand-700">
                  {selectedProduct.price.toLocaleString()} ₽
                </span>
                {selectedProduct.stock > 0 && (
                  <button
                    onClick={() => { addToCart(selectedProduct); setSelectedProduct(null); }}
                    className="bg-brand-600 hover:bg-brand-700 text-white font-bold px-6 py-3 rounded-2xl active:scale-95 transition-transform"
                  >
                    В корзину
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
