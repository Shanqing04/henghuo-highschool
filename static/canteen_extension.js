/* 横火食堂动态菜单扩展：保留所有原有菜品与点餐布局。 */
(function () {
  "use strict";
  if (typeof menu === "undefined" || typeof renderCanteen !== "function") return;
  const original = {
    breakfast: menu.breakfast.slice(),
    lunch: menu.lunch.slice(),
    dinner: menu.dinner.slice()
  };
  let lastSignature = "";
  const safe = value => String(value == null ? "" : value)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;")
    .replace(/'/g,"&#39;");
  async function refreshDynamicMenu() {
    try {
      const response = await fetch("/api/canteen/dishes", {cache:"no-store"});
      if (!response.ok) return;
      const result = await response.json();
      if (!result.success || !Array.isArray(result.data)) return;
      const signature = JSON.stringify(result.data);
      if (signature === lastSignature) return;
      lastSignature = signature;
      for (const meal of ["breakfast","lunch","dinner"]) {
        menu[meal] = original[meal].slice();
      }
      for (const dish of result.data) {
        if (!dish.active || !Array.isArray(dish.meals)) continue;
        const entry = [
          safe(dish.name),
          Number(dish.price),
          safe(dish.category),
          safe(dish.emoji || "🍽️"),
          safe(dish.description)
        ];
        if (!Number.isFinite(entry[1])) continue;
        for (const meal of dish.meals) {
          if (menu[meal]) menu[meal].push(entry);
        }
      }
      // 菜品索引改变时，避免原购物车指向错误菜品
      if (typeof cart !== "undefined" && Object.keys(cart).length) {
        cart = {};
        if (typeof toast === "function") toast("食堂菜单已更新，请重新选择菜品");
      }
      if (typeof foodCategory !== "undefined") foodCategory = "全部";
      renderCanteen();
    } catch (error) {
      console.warn("动态菜单加载失败，继续使用原有菜单", error);
    }
  }
  const previousRender = renderCanteen;
  renderCanteen = function () {
    previousRender.apply(this, arguments);
    // 每次进入食堂都同步管理员最新设置
    refreshDynamicMenu();
  };
  refreshDynamicMenu();
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) refreshDynamicMenu();
  });
})();
