/**
 * ChargeSlot Frontend Application
 * Minimalist Single Page Application consuming ChargeSlot FastAPI Backend
 */

(function () {
  'use strict';

  // --------------------------------------------------------------------------
  // Configuration & State
  // --------------------------------------------------------------------------
  const API_BASE = '/api/v1';
  const STATE = {
    token: localStorage.getItem('chargeslot_token') || null,
    user: JSON.parse(localStorage.getItem('chargeslot_user') || 'null'),
    reservedStationIds: new Set(),
    activeReservations: {}, // stationId -> { bookingId, slotTime, slotDate, slotEndMs }
    stations: [],
    selectedStation: null,
    selectedSlot: null,
    currentLocation: { lat: 12.9352, lon: 77.6245 }, // Default Bengaluru Koramangala
    map: null,
    markersLayer: null,
    routeLayer: null,
    ws: null,
  };

  // Pre-configured vehicles (SRS Appendix B presets)
  const VEHICLES = {
    '1': { name: 'Tata Nexon EV', capacity: 40.5, consumption: 15.0 },
    '2': { name: 'MG ZS EV', capacity: 50.3, consumption: 16.5 },
    '3': { name: 'Hyundai Ioniq 5', capacity: 72.6, consumption: 17.5 },
  };

  // --------------------------------------------------------------------------
  // DOM Elements
  // --------------------------------------------------------------------------
  const DOM = {
    // Navigation Tabs
    navTabs: document.querySelectorAll('.nav-tab'),
    tabContents: document.querySelectorAll('.tab-content'),

    // Auth
    btnAuthModal: document.getElementById('btn-auth-modal'),
    btnLogout: document.getElementById('btn-logout'),
    currentUserBadge: document.getElementById('current-user-badge'),
    authModal: document.getElementById('auth-modal'),
    btnCloseAuthModal: document.getElementById('btn-close-auth-modal'),
    tabBtnSignin: document.getElementById('tab-btn-signin'),
    tabBtnSignup: document.getElementById('tab-btn-signup'),
    formSignin: document.getElementById('form-signin'),
    formSignup: document.getElementById('form-signup'),

    // Global Alert
    globalAlert: document.getElementById('global-alert'),
    globalAlertText: document.getElementById('global-alert-text'),
    btnCloseAlert: document.getElementById('btn-close-alert'),

    // Stations & Map
    searchInput: document.getElementById('search-input'),
    btnSearchStations: document.getElementById('btn-search-stations'),
    filterConnector: document.getElementById('filter-connector'),
    filterMinPower: document.getElementById('filter-min-power'),
    filterRadius: document.getElementById('filter-radius'),
    radiusDisplay: document.getElementById('radius-display'),
    filterAvailableNow: document.getElementById('filter-available-now'),
    btnApplyFilters: document.getElementById('btn-apply-filters'),
    btnResetFilters: document.getElementById('btn-reset-filters'),
    stationCount: document.getElementById('station-count'),
    stationsList: document.getElementById('stations-list'),
    btnCenterUserLocation: document.getElementById('btn-center-user-location'),

    // Route Preview & Nav
    navTargetStation: document.getElementById('nav-target-station'),
    navOriginLat: document.getElementById('nav-origin-lat'),
    navOriginLon: document.getElementById('nav-origin-lon'),
    navTraffic: document.getElementById('nav-traffic'),
    navSimulateOffline: document.getElementById('nav-simulate-offline'),
    btnCalculateRoute: document.getElementById('btn-calculate-route'),
    routeSummaryContent: document.getElementById('route-summary-content'),
    linkGmaps: document.getElementById('link-gmaps'),
    linkApple: document.getElementById('link-apple'),
    linkWaze: document.getElementById('link-waze'),
    linkGeo: document.getElementById('link-geo'),

    // Battery & Booking
    batteryVehicleSelect: document.getElementById('battery-vehicle-select'),
    batterySocSlider: document.getElementById('battery-soc-slider'),
    socDisplay: document.getElementById('soc-display'),
    batteryTargetSoc: document.getElementById('battery-target-soc'),
    targetSocDisplay: document.getElementById('target-soc-display'),
    bookingStationSelect: document.getElementById('booking-station-select'),
    valUsableRange: document.getElementById('val-usable-range'),
    valEnergyRequired: document.getElementById('val-energy-required'),
    valChargingTime: document.getElementById('val-charging-time'),
    valChargingCost: document.getElementById('val-charging-cost'),
    slotDatePicker: document.getElementById('slot-date-picker'),
    slotGridDisplay: document.getElementById('slot-grid-display'),
    bookingConfirmationBox: document.getElementById('booking-confirmation-box'),
    selectedSlotDetails: document.getElementById('selected-slot-details'),
    btnConfirmSlotClaim: document.getElementById('btn-confirm-slot-claim'),


    // Billing & Invoice
    invoiceBookingId: document.getElementById('invoice-booking-id'),
    btnDownloadInvoice: document.getElementById('btn-download-invoice'),
    invoiceDownloadStatus: document.getElementById('invoice-download-status'),
    paymentHistoryTbody: document.getElementById('payment-history-tbody'),

    // Demo Payment Modal
    btnOpenPaymentModal: document.getElementById('btn-open-payment-modal'),
    paymentModal: document.getElementById('payment-modal'),
    btnClosePaymentModal: document.getElementById('btn-close-payment-modal'),
    paymentModalBody: document.getElementById('payment-modal-body'),
    paymentModalSuccess: document.getElementById('payment-modal-success'),
    payModalStation: document.getElementById('pay-modal-station'),
    payModalBookingId: document.getElementById('pay-modal-booking-id'),
    payModalEnergy: document.getElementById('pay-modal-energy'),
    payModalEnergyCost: document.getElementById('pay-modal-energy-cost'),
    payModalTax: document.getElementById('pay-modal-tax'),
    payModalTotal: document.getElementById('pay-modal-total'),
    payModalStatus: document.getElementById('pay-modal-status'),
    btnSubmitPayment: document.getElementById('btn-submit-payment'),
    payModalTxnId: document.getElementById('pay-modal-txn-id'),
    btnPayModalDownloadInvoice: document.getElementById('btn-pay-modal-download-invoice'),
    btnPayModalDone: document.getElementById('btn-pay-modal-done'),

    // Profile & Settings
    profileGuestView: document.getElementById('profile-guest-view'),
    profileAuthView: document.getElementById('profile-auth-view'),
    btnProfileGuestSignin: document.getElementById('btn-profile-guest-signin'),
    profileAvatar: document.getElementById('profile-avatar'),
    profileDisplayName: document.getElementById('profile-display-name'),
    profileDisplayRole: document.getElementById('profile-display-role'),
    profileDisplayEmail: document.getElementById('profile-display-email'),
    profileCreatedDate: document.getElementById('profile-created-date'),
    formEditProfile: document.getElementById('form-edit-profile'),
    profileInputName: document.getElementById('profile-input-name'),
    profileInputPhone: document.getElementById('profile-input-phone'),
    profileChargingMode: document.getElementById('profile-charging-mode'),
    profileTargetBattery: document.getElementById('profile-target-battery'),
    profileTargetBatteryDisplay: document.getElementById('profile-target-battery-display'),
    profileLowBattery: document.getElementById('profile-low-battery'),
    profileLowBatteryDisplay: document.getElementById('profile-low-battery-display'),
    profileSearchRadius: document.getElementById('profile-search-radius'),
    profileSearchRadiusDisplay: document.getElementById('profile-search-radius-display'),
    profileNotifyEmail: document.getElementById('profile-notify-email'),
    profileNotifySms: document.getElementById('profile-notify-sms'),
    profileNotifyPush: document.getElementById('profile-notify-push'),
    profileSaveStatus: document.getElementById('profile-save-status'),
    formChangePassword: document.getElementById('form-change-password'),
    pwdCurrent: document.getElementById('pwd-current'),
    pwdNew: document.getElementById('pwd-new'),
    pwdConfirm: document.getElementById('pwd-confirm'),
    pwdChangeStatus: document.getElementById('pwd-change-status'),
    btnProfileLogoutCard: document.getElementById('btn-profile-logout-card'),
  };

  // --------------------------------------------------------------------------
  // API Fetch Utility
  // --------------------------------------------------------------------------
  async function apiRequest(endpoint, options = {}) {
    const headers = options.headers || {};
    if (STATE.token) {
      headers['Authorization'] = `Bearer ${STATE.token}`;
    }
    if (options.body && !(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
    }

    try {
      const response = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers,
      });

      if (response.status === 401 && STATE.token) {
        logoutUser();
        showAlert('Session expired. Please sign in again.', 'error');
        throw new Error('Unauthorized');
      }

      if (response.headers.get('content-type')?.includes('application/pdf')) {
        return response.blob();
      }

      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const errorDetail = data.detail || response.statusText || 'Request failed';
        throw new Error(typeof errorDetail === 'string' ? errorDetail : JSON.stringify(errorDetail));
      }
      return data;
    } catch (err) {
      console.error(`API Error on ${endpoint}:`, err);
      throw err;
    }
  }

  function showAlert(message, type = 'info') {
    DOM.globalAlertText.innerHTML = message;
    DOM.globalAlert.classList.remove('hidden');
    DOM.globalAlert.style.backgroundColor = type === 'error' ? '#7f1d1d' : '#064e3b';
  }

  // --------------------------------------------------------------------------
  // Dynamic Reservation Timing & Slot Expiry Management
  // --------------------------------------------------------------------------
  function loadActiveReservations() {
    try {
      const raw = localStorage.getItem('chargeslot_active_reservations');
      STATE.activeReservations = raw ? JSON.parse(raw) : {};
    } catch {
      STATE.activeReservations = {};
    }
    checkAndExpireReservations();
  }

  function saveActiveReservations() {
    localStorage.setItem('chargeslot_active_reservations', JSON.stringify(STATE.activeReservations));
    localStorage.setItem('chargeslot_reserved_stations', JSON.stringify(Array.from(STATE.reservedStationIds)));
  }

  function checkAndExpireReservations() {
    const now = Date.now();
    let changed = false;
    const expiredNames = [];

    STATE.reservedStationIds.clear();

    for (const [stIdStr, res] of Object.entries(STATE.activeReservations)) {
      const stId = parseInt(stIdStr, 10);
      const expiryMs = res.slotEndMs || 0;

      if (expiryMs && now >= expiryMs) {
        delete STATE.activeReservations[stIdStr];
        changed = true;

        const st = STATE.stations.find(s => s.id === stId);
        if (st && st.color_code !== 'red') {
          st.color_code = 'green';
          st.status_label = 'Available';
          st.badge_text = 'Available';
          expiredNames.push(st.name || `Station #${stId}`);
        }
      } else {
        STATE.reservedStationIds.add(stId);
      }
    }

    if (changed) {
      saveActiveReservations();
      if (STATE.map && STATE.stations.length) {
        renderStationMarkers(STATE.stations);
        renderStationsList(STATE.stations);
      }
      if (expiredNames.length) {
        showAlert(`⏱️ Reserved time slot has ended for <strong>${escapeHtml(expiredNames.join(', '))}</strong>. Station dot on the map has returned to <strong>Available (GREEN)</strong>.`, 'info');
      }
    }
  }

  window.expireReservationNow = function (stId) {
    const targetId = stId || (STATE.selectedStation && STATE.selectedStation.id) || Array.from(STATE.reservedStationIds)[0];
    if (!targetId || !STATE.reservedStationIds.has(targetId)) {
      showAlert('No active slot reservation to expire.', 'info');
      return;
    }

    delete STATE.activeReservations[targetId];
    STATE.reservedStationIds.delete(targetId);

    const st = STATE.stations.find(s => s.id === targetId);
    if (st && st.color_code !== 'red') {
      st.color_code = 'green';
      st.status_label = 'Available';
      st.badge_text = 'Available';
    }

    saveActiveReservations();
    renderStationMarkers(STATE.stations);
    renderStationsList(STATE.stations);
    showAlert(`⏱️ Time slot has elapsed! <strong>${escapeHtml((st && st.name) || 'Station #' + targetId)}</strong> has returned to <strong>Available (GREEN)</strong> on the map.`, 'info');
  };

  // --------------------------------------------------------------------------
  // Map Initialization (Leaflet.js)
  // --------------------------------------------------------------------------
  function initMap() {
    if (STATE.map) return;

    // Centered around Bengaluru
    STATE.map = L.map('map-container').setView([STATE.currentLocation.lat, STATE.currentLocation.lon], 12);

    // 100% Free OpenStreetMap public tile server (no API key required)
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).addTo(STATE.map);

    STATE.markersLayer = L.layerGroup().addTo(STATE.map);
    STATE.routeLayer = L.layerGroup().addTo(STATE.map);

    // Current driver location marker
    L.circleMarker([STATE.currentLocation.lat, STATE.currentLocation.lon], {
      radius: 8,
      fillColor: '#3b82f6',
      color: '#ffffff',
      weight: 2,
      opacity: 1,
      fillOpacity: 0.9,
    }).addTo(STATE.map).bindPopup('📍 Your Current Location');
  }

  // --------------------------------------------------------------------------
  // Stations Module
  // --------------------------------------------------------------------------
  async function loadStations() {
    try {
      const radiusKm = parseFloat(DOM.filterRadius?.value) || 25;
      DOM.stationsList.innerHTML = '<div class="empty-state">Finding nearby stations in Bangalore...</div>';

      const data = await apiRequest(`/stations/nearby-station-search?latitude=${STATE.currentLocation.lat}&longitude=${STATE.currentLocation.lon}&radius_km=${radiusKm}&limit=50`);
      const stations = data.stations || (Array.isArray(data) ? data : []);

      // Merge local active reservations, strictly respecting out of service & expiry
      checkAndExpireReservations();

      stations.forEach(s => {
        const isOos = s.is_out_of_service || s.color_code === 'red' || s.status_label === 'Out of Service' || s.badge_text === 'Out of Service' || !s.is_active || s.total_chargers === 0;
        if (isOos) {
          STATE.reservedStationIds.delete(s.id);
          delete STATE.activeReservations[s.id];
          s.color_code = 'red';
          s.status_label = 'Out of Service';
          s.badge_text = 'Out of Service';
        } else if (STATE.reservedStationIds.has(s.id)) {
          s.color_code = 'purple';
          s.status_label = 'Reserved';
          s.badge_text = 'Slot Reserved';
        } else {
          s.color_code = 'green';
          s.status_label = 'Available';
          s.badge_text = 'Available';
        }
      });
      saveActiveReservations();

      STATE.stations = stations;
      renderStationMarkers(stations);
      renderStationsList(stations);
      populateStationDropdowns(stations);
    } catch (err) {
      DOM.stationsList.innerHTML = `
        <div class="empty-state">
          Unable to load stations: ${escapeHtml(err.message)}<br/>
          <button class="btn btn-primary btn-sm" onclick="window.quickDemoLogin()" style="margin-top: 8px;">
            ⚡ Quick Sign In as Demo Driver
          </button>
        </div>`;
    }
  }

  function renderStationMarkers(stations) {
    if (!STATE.markersLayer) return;
    STATE.markersLayer.clearLayers();

    const bounds = [];

    stations.forEach(station => {
      const lat = station.latitude;
      const lon = station.longitude;
      if (!lat || !lon) return;

      bounds.push([lat, lon]);

      // Legend Color Rules:
      // 1. Out of Service -> RED (#ef4444)
      // 2. Reserved -> PURPLE (#8b5cf6)
      // 3. Occupied / Partially Available -> AMBER (#f59e0b)
      // 4. Available -> GREEN (#10b981)
      let markerColor = '#10b981'; // Green
      let statusTag = 'Available';

      if (
        station.color_code === 'red' ||
        station.status_label === 'Out of Service' ||
        station.badge_text === 'Out of Service' ||
        !station.is_active ||
        station.total_chargers === 0
      ) {
        markerColor = '#ef4444'; // Red for Out of Service
        statusTag = 'Out of Service';
      } else if (
        station.color_code === 'purple' ||
        station.status_label === 'Reserved' ||
        STATE.reservedStationIds.has(station.id)
      ) {
        markerColor = '#8b5cf6'; // Purple for Reserved
        statusTag = 'Reserved';
      } else if (
        station.color_code === 'amber' ||
        station.status_label === 'Partially Available' ||
        station.status_label === 'Occupied'
      ) {
        markerColor = '#f59e0b'; // Amber for Occupied / Partially Available
        statusTag = station.status_label || 'Occupied';
      } else if (station.color_code === 'grey') {
        markerColor = '#64748b';
        statusTag = 'Offline';
      }

      const marker = L.circleMarker([lat, lon], {
        radius: 11,
        fillColor: markerColor,
        color: '#ffffff',
        weight: 2.5,
        opacity: 1,
        fillOpacity: 0.95,
      });

      marker.bindTooltip(`<strong>${escapeHtml(station.name)}</strong><br/><span style="color: ${markerColor};">●</span> <strong>${statusTag}</strong> (${escapeHtml(station.badge_text || statusTag)})`, {
        permanent: false,
        direction: 'top',
        offset: [0, -8],
      });

      const isOos = statusTag === 'Out of Service';
      const popupHtml = `
        <div style="font-family: system-ui, sans-serif; min-width: 230px; line-height: 1.4; color: #0f172a;">
          <h4 style="margin: 0 0 6px 0; font-size: 14px; font-weight: 600;">${escapeHtml(station.name)}</h4>
          <p style="margin: 0 0 6px 0; font-size: 12px; color: #475569;">${escapeHtml(station.address)}</p>
          <div style="font-size: 12px; margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center;">
            <span><strong>Tariff:</strong> ₹${station.price_per_kwh || '18.00'}/kWh</span>
            <span style="font-weight: 700; color: ${markerColor}; padding: 2px 6px; border-radius: 4px; background: rgba(0,0,0,0.06);">
              ● ${statusTag}
            </span>
          </div>
          <div style="font-size: 11px; color: #64748b; margin-bottom: 8px;">
            Plugs: ${(station.connector_types || []).join(', ') || 'CCS2, Type 2'} (${station.distance_km || 0} km away)
          </div>
          ${isOos
            ? `<div style="padding: 6px 10px; background: #fee2e2; color: #991b1b; border-radius: 4px; font-size: 11px; font-weight: 600; text-align: center;">
                ⚠️ Out of Service (Maintenance in Progress)
               </div>`
            : `<button style="width: 100%; background: ${markerColor}; color: #ffffff; border: none; padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: 500; cursor: pointer;"
                       onclick="window.selectStationFromMap(${station.id})">
                 🧭 Preview Route &amp; Slots
               </button>`
          }
        </div>
      `;

      marker.bindPopup(popupHtml);
      STATE.markersLayer.addLayer(marker);
    });

    if (bounds.length > 0 && STATE.map) {
      STATE.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
      setTimeout(() => STATE.map?.invalidateSize(), 150);
    }
  }

  window.selectStationFromMap = function (stationId) {
    const station = STATE.stations.find(s => s.id === stationId);
    if (station) {
      selectStation(station);
    }
  };

  function renderStationsList(stations) {
    DOM.stationCount.textContent = stations.length;

    if (!stations.length) {
      DOM.stationsList.innerHTML = '<div class="empty-state">No stations found matching criteria.</div>';
      return;
    }

    DOM.stationsList.innerHTML = stations.map(station => {
      const distanceDisplay = station.distance_km ? `${station.distance_km.toFixed(1)} km` : '';
      const tariff = station.price_per_kwh ? `₹${station.price_per_kwh}/kWh` : 'Standard Tariff';

      let statusTag = 'Available';
      let badgeHtml = '<span class="tag-badge avail">🟢 Available</span>';

      if (
        station.color_code === 'red' ||
        station.status_label === 'Out of Service' ||
        station.badge_text === 'Out of Service' ||
        !station.is_active ||
        station.total_chargers === 0
      ) {
        statusTag = 'Out of Service';
        badgeHtml = '<span class="tag-badge" style="background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid #ef4444;">🔴 Out of Service</span>';
      } else if (
        station.color_code === 'purple' ||
        station.status_label === 'Reserved' ||
        STATE.reservedStationIds.has(station.id)
      ) {
        statusTag = 'Reserved';
        badgeHtml = '<span class="tag-badge" style="background: rgba(139, 92, 246, 0.25); color: #c084fc; border: 1px solid #8b5cf6;">🟣 Slot Reserved</span>';
      } else if (
        station.color_code === 'amber' ||
        station.status_label === 'Partially Available' ||
        station.status_label === 'Occupied'
      ) {
        statusTag = station.status_label || 'Occupied';
        badgeHtml = `<span class="tag-badge" style="background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid #f59e0b;">🟡 ${escapeHtml(station.badge_text || 'Occupied')}</span>`;
      }

      return `
        <div class="station-item-card ${statusTag === 'Out of Service' ? 'station-oos' : ''}" data-station-id="${station.id}">
          <div class="station-item-header">
            <span class="station-name">${escapeHtml(station.name)}</span>
            <span class="station-distance">${distanceDisplay}</span>
          </div>
          <p class="station-address">${escapeHtml(station.address)}</p>
          <div class="station-tags">
            ${badgeHtml}
            <span class="tag-badge">${tariff}</span>
            <span class="tag-badge">${station.total_chargers || 0} Chargers</span>
          </div>
        </div>
      `;
    }).join('');

    // Attach click events
    document.querySelectorAll('.station-item-card').forEach(card => {
      card.addEventListener('click', () => {
        const stationId = parseInt(card.dataset.stationId, 10);
        const station = STATE.stations.find(s => s.id === stationId);
        if (station) selectStation(station);
      });
    });
  }

  function selectStation(station) {
    STATE.selectedStation = station;
    DOM.navTargetStation.value = station.id;
    DOM.bookingStationSelect.value = station.id;

    if (STATE.map && station.latitude && station.longitude) {
      STATE.map.setView([station.latitude, station.longitude], 14);
    }

    // Update navigation preview
    updateNavigationLinks(station.id, station.name, station.latitude, station.longitude);
    renderSlotTimeline();
    calculateBatteryEstimates();
  }

  function populateStationDropdowns(stations) {
    const optionsHtml = stations.map(s => {
      const isOos = s.color_code === 'red' || s.status_label === 'Out of Service' || s.badge_text === 'Out of Service' || !s.is_active || s.total_chargers === 0;
      const labelPrefix = isOos ? '⚠️ [OUT OF SERVICE] ' : '';
      const tariffText = isOos ? '(Maintenance)' : `(₹${s.price_per_kwh || '18.00'}/kWh)`;
      return `
        <option value="${s.id}" data-lat="${s.latitude}" data-lon="${s.longitude}" data-oos="${isOos ? 'true' : 'false'}">
          ${labelPrefix}${escapeHtml(s.name)} ${tariffText}
        </option>
      `;
    }).join('');

    DOM.navTargetStation.innerHTML = `<option value="">Select a destination...</option>` + optionsHtml;
    DOM.bookingStationSelect.innerHTML = optionsHtml;
  }

  // --------------------------------------------------------------------------
  // Route Preview & Navigation Module (REQ-F2-25 / REQ-F2-26 / REQ-F2-28)
  // --------------------------------------------------------------------------
  async function calculateRoutePreview() {
    const stationId = DOM.navTargetStation.value;
    if (!stationId) {
      showAlert('Please select a destination station first.', 'error');
      return;
    }

    const lat = parseFloat(DOM.navOriginLat.value);
    const lon = parseFloat(DOM.navOriginLon.value);
    const traffic = DOM.navTraffic.value;
    const simulateOffline = DOM.navSimulateOffline.checked;

    DOM.routeSummaryContent.innerHTML = '<div class="empty-state">Computing route and checking 2-minute cache...</div>';

    try {
      const queryParams = new URLSearchParams({
        station_id: stationId,
        latitude: lat,
        longitude: lon,
        traffic_condition: traffic,
        simulate_maps_unavailable: simulateOffline,
      });

      // Endpoint: GET /api/v1/stations/route-cache-and-fallback (REQ-F2-28)
      const data = await apiRequest(`/stations/route-cache-and-fallback?${queryParams.toString()}`);

      renderRouteResult(data);
      drawRouteOnMap(data);
      updateNavigationLinks(stationId, data.station_name, data.destination_latitude, data.destination_longitude, lat, lon);
    } catch (err) {
      DOM.routeSummaryContent.innerHTML = `<div class="empty-state" style="color: #ef4444;">Route calculation error: ${err.message}</div>`;
    }
  }

  function renderRouteResult(route) {
    const isFallback = route.is_fallback;
    const cacheHit = route.cache_hit;
    const cacheNotice = cacheHit
      ? `⚡ Served from 2-minute route cache (Cache age: ${route.cache_age_seconds}s)`
      : `🔄 Fresh route calculated (TTL: 120s)`;

    DOM.routeSummaryContent.innerHTML = `
      <div style="display: flex; flex-direction: column; gap: 0.75rem;">
        <div style="font-size: 0.75rem; color: #94a3b8; border-bottom: 1px solid rgba(148,163,184,0.15); padding-bottom: 0.5rem;">
          ${cacheNotice}
        </div>

        ${isFallback ? `
          <div style="background-color: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444; padding: 0.6rem; border-radius: 6px; font-size: 0.75rem; color: #fca5a5;">
            <strong>Notice:</strong> ${escapeHtml(route.fallback_notice || 'Maps service unavailable. Showing straight-line distance fallback (SR-F2-09).')}
          </div>
        ` : ''}

        <div class="metrics-grid" style="margin-top: 0;">
          <div class="metric-card">
            <span class="metric-label">${isFallback ? 'Straight-Line Distance' : 'Road Distance'}</span>
            <span class="metric-value">${route.road_distance_km} km</span>
          </div>
          <div class="metric-card">
            <span class="metric-label">Estimated Travel Time</span>
            <span class="metric-value">${route.estimated_travel_time_minutes} min</span>
          </div>
          <div class="metric-card">
            <span class="metric-label">Traffic Condition</span>
            <span class="metric-value" style="font-size: 1rem; text-transform: capitalize;">${route.traffic_condition}</span>
            <span class="metric-sub">Delay: ${route.traffic_delay_minutes} min</span>
          </div>
          <div class="metric-card">
            <span class="metric-label">Average Speed</span>
            <span class="metric-value">${route.average_speed_kmh} km/h</span>
          </div>
        </div>

        <h4 style="font-size: 0.875rem; margin-top: 0.5rem;">Waypoints (${route.waypoints?.length || 0})</h4>
        <ul style="font-size: 0.75rem; color: #cbd5e1; list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0.35rem;">
          ${(route.waypoints || []).map(wp => `
            <li style="padding: 0.35rem 0.5rem; background: #0f172a; border-radius: 4px;">
              <strong>Step ${wp.step_index + 1}:</strong> ${escapeHtml(wp.instruction)}
              <span style="color: #94a3b8; margin-left: 6px;">(${wp.distance_km} km)</span>
            </li>
          `).join('')}
        </ul>
      </div>
    `;
  }

  function drawRouteOnMap(route) {
    if (!STATE.routeLayer || !route.route_geometry || !route.route_geometry.length) return;
    STATE.routeLayer.clearLayers();

    const polyline = L.polyline(route.route_geometry, {
      color: route.is_fallback ? '#f59e0b' : '#10b981',
      weight: 4,
      opacity: 0.8,
      dashArray: route.is_fallback ? '6, 8' : null,
    }).addTo(STATE.routeLayer);

    STATE.map.fitBounds(polyline.getBounds(), { padding: [40, 40] });
  }

  async function updateNavigationLinks(stationId, stationName, destLat, destLon, origLat, origLon) {
    try {
      const q = new URLSearchParams();
      if (origLat) q.append('origin_latitude', origLat);
      if (origLon) q.append('origin_longitude', origLon);

      const resp = await apiRequest(`/stations/${stationId}/navigation-hand-off?${q.toString()}`);
      if (resp && resp.deep_links) {
        DOM.linkGmaps.href = resp.deep_links.google_maps || '#';
        DOM.linkApple.href = resp.deep_links.apple_maps || '#';
        DOM.linkWaze.href = resp.deep_links.waze || '#';
        DOM.linkGeo.href = resp.deep_links.generic_geo || '#';
      }
    } catch {
      // Fallback manual links
      const encName = encodeURIComponent(stationName);
      DOM.linkGmaps.href = `https://www.google.com/maps/dir/?api=1&destination=${destLat},${destLon}`;
      DOM.linkApple.href = `maps://?daddr=${destLat},${destLon}&q=${encName}`;
      DOM.linkWaze.href = `https://waze.com/ul?ll=${destLat},${destLon}&navigate=yes`;
      DOM.linkGeo.href = `geo:${destLat},${destLon}?q=${destLat},${destLon}(${encName})`;
    }
  }

  // --------------------------------------------------------------------------
  // Battery Estimator & Slot Booking Module (REQ-F3-01 / REQ-F3-07 / REQ-F2-22)
  // --------------------------------------------------------------------------
  function calculateBatteryEstimates() {
    const vehicleKey = DOM.batteryVehicleSelect.value;
    const vehicle = VEHICLES[vehicleKey] || VEHICLES['1'];

    const currentSoc = parseInt(DOM.batterySocSlider.value, 10);
    const targetSoc = parseInt(DOM.batteryTargetSoc.value, 10);
    DOM.socDisplay.textContent = `${currentSoc}%`;
    DOM.targetSocDisplay.textContent = `${targetSoc}%`;

    const stationOpt = DOM.bookingStationSelect.selectedOptions[0];
    const tariffRate = stationOpt ? parseFloat(stationOpt.dataset.tariff || '18.5') : 18.5;
    const chargerPowerKw = 50.0; // Typical DC fast charger baseline

    // 1. Usable Range (SRS Appendix B.1):
    // Usable Range = max(0, SoC - 10) / 100 * Capacity / (Consumption / 100)
    const effectiveSoc = Math.max(0, currentSoc - 10);
    const usableEnergy = (effectiveSoc / 100.0) * vehicle.capacity;
    const usableRangeKm = Math.round((usableEnergy / (vehicle.consumption / 100.0)) * 10) / 10;
    DOM.valUsableRange.textContent = `${usableRangeKm} km`;

    // 2. Energy Required (SRS Appendix B.2):
    // Energy Required = max(0, Target SoC - Current SoC) / 100 * Capacity / 0.90
    const deltaSoc = Math.max(0, targetSoc - currentSoc);
    const energyRequiredKwh = Math.round(((deltaSoc / 100.0) * vehicle.capacity / 0.90) * 100) / 100;
    DOM.valEnergyRequired.textContent = `${energyRequiredKwh} kWh`;

    // 3. Charging Time (minutes) rounded up to 15-minute slot:
    const rawHours = energyRequiredKwh / chargerPowerKw;
    const rawMinutes = rawHours * 60.0;
    const roundedSlotMinutes = Math.max(15, Math.ceil(rawMinutes / 15.0) * 15);
    DOM.valChargingTime.textContent = `${roundedSlotMinutes} min`;

    // 4. Estimated Cost:
    const estimatedCost = Math.round(energyRequiredKwh * tariffRate * 100) / 100;
    DOM.valChargingCost.textContent = `₹ ${estimatedCost.toFixed(2)}`;
  }

  function renderSlotTimeline() {
    DOM.slotGridDisplay.innerHTML = '';
    DOM.bookingConfirmationBox?.classList.add('hidden');

    const selectedStationId = parseInt(DOM.bookingStationSelect?.value, 10);
    const station = STATE.stations.find(s => s.id === selectedStationId);
    const isOos = station && (
      station.color_code === 'red' ||
      station.status_label === 'Out of Service' ||
      station.badge_text === 'Out of Service' ||
      !station.is_active ||
      station.total_chargers === 0
    );

    if (isOos) {
      DOM.slotGridDisplay.innerHTML = `
        <div class="empty-state" style="color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.35); background: rgba(239, 68, 68, 0.08); padding: 1.5rem; border-radius: 8px; text-align: center;">
          <div style="font-size: 1.25rem; font-weight: 700; margin-bottom: 0.35rem;">⚠️ Station Out of Service</div>
          <p style="margin: 0; font-size: 0.9375rem; color: #f87171;">
            <strong>${escapeHtml(station.name)}</strong> is currently shut down for maintenance.
          </p>
          <p style="margin: 0.5rem 0 0 0; font-size: 0.8125rem; color: #94a3b8;">
            Reservations and slot booking are disabled while this station is out of service. Please choose another station.
          </p>
        </div>
      `;
      return;
    }

    const startHour = 8;
    const endHour = 20;

    for (let h = startHour; h < endHour; h++) {
      for (let m = 0; m < 60; m += 15) {
        const timeStr = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
        const isOccupied = (h === 11 && m === 15) || (h === 14 && m === 30); // sample simulated taken slots

        const pill = document.createElement('div');
        pill.className = `slot-pill ${isOccupied ? 'disabled' : ''}`;
        pill.textContent = timeStr;
        pill.dataset.slotTime = timeStr;

        if (!isOccupied) {
          pill.addEventListener('click', () => {
            document.querySelectorAll('.slot-pill').forEach(p => p.classList.remove('selected'));
            pill.classList.add('selected');
            STATE.selectedSlot = timeStr;

            DOM.bookingConfirmationBox.classList.remove('hidden');
            DOM.selectedSlotDetails.textContent = `Date: ${DOM.slotDatePicker.value} at ${timeStr} (Duration: 15-min interval)`;
          });
        }

        DOM.slotGridDisplay.appendChild(pill);
      }
    }
  }

  async function confirmSlotClaim() {
    if (!requireAuth('confirm your booking')) return;

    const stationId = parseInt(DOM.bookingStationSelect.value, 10);
    const st = STATE.stations.find(s => s.id === stationId);
    const isOos = st && (
      st.color_code === 'red' ||
      st.status_label === 'Out of Service' ||
      st.badge_text === 'Out of Service' ||
      !st.is_active ||
      st.total_chargers === 0
    );

    if (isOos) {
      showAlert(`⚠️ Cannot reserve slot: ${st ? st.name : 'This station'} is currently Out of Service for maintenance.`, 'error');
      DOM.bookingConfirmationBox?.classList.add('hidden');
      renderSlotTimeline();
      return;
    }

    const slotTime = STATE.selectedSlot;
    const slotDate = DOM.slotDatePicker?.value || new Date().toISOString().split('T')[0];
    const vehicleId = parseInt(DOM.batteryVehicleSelect?.value, 10) || 1;
    const targetSoc = parseInt(DOM.batteryTargetSoc?.value, 10) || 80;

    if (!slotTime) {
      showAlert('Please choose an available slot time from the timeline.', 'error');
      return;
    }

    try {
      // 1. Fetch station details to find operational charger
      const detail = await apiRequest(`/stations/${stationId}/detail`);
      const operationalChargers = (detail.chargers || []).filter(c => c.is_active && !c.is_out_of_service);
      if (operationalChargers.length === 0) {
        showAlert(`⚠️ Charging station "${escapeHtml(detail.name || (st && st.name) || '')}" is currently Out of Service. No active chargers are available.`, 'error');
        DOM.bookingConfirmationBox?.classList.add('hidden');
        renderSlotTimeline();
        return;
      }
      const chargerId = operationalChargers[0].id;

      // 2. Call backend manual slot booking API
      const bookingData = await apiRequest('/bookings/manual-slot', {
        method: 'POST',
        body: JSON.stringify({
          station_id: stationId,
          charger_id: chargerId,
          vehicle_id: vehicleId,
          start_time: `${slotDate}T${slotTime}:00Z`,
          target_soc: targetSoc,
        }),
      });

      const bookingId = bookingData.booking_id;

      // 3. Mark station reserved with slot timing in activeReservations
      const [h, m] = slotTime.split(':').map(Number);
      const slotStart = new Date(slotDate);
      slotStart.setHours(h, m, 0, 0);
      const now = Date.now();
      let slotEndMs = slotStart.getTime() + 15 * 60 * 1000; // 15-minute slot interval
      if (slotEndMs <= now) {
        // If testing on a slot earlier today, keep active for 15 minutes from now
        slotEndMs = now + 15 * 60 * 1000;
      }

      STATE.activeReservations[stationId] = {
        stationId,
        bookingId,
        slotTime,
        slotDate,
        slotEndMs,
      };
      STATE.reservedStationIds.add(stationId);
      saveActiveReservations();

      // 4. Update memory station object
      if (st) {
        st.color_code = 'purple';
        st.status_label = 'Reserved';
        st.badge_text = 'Slot Reserved';
      }

      // 5. Instantly re-render map with PURPLE dot and list
      renderStationMarkers(STATE.stations);
      renderStationsList(STATE.stations);

      // Pre-fill invoice booking ID for instant download
      if (DOM.invoiceBookingId) {
        DOM.invoiceBookingId.value = bookingId;
      }

      DOM.bookingConfirmationBox.classList.add('hidden');
      const timeExpStr = new Date(slotEndMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      showAlert(
        `🎉 Slot at <strong>${slotTime}</strong> reserved! Booking #${bookingId} confirmed. Station dot is PURPLE until ${timeExpStr} (will revert to GREEN once time slot has elapsed). ` +
        `<button class="btn btn-secondary btn-sm" onclick="window.expireReservationNow(${stationId})" style="margin-left:8px; padding:2px 8px; font-size:11px;">⏱️ Expire Slot Now (Test)</button>`,
        'info'
      );

      // Auto-switch to Map tab so user immediately sees the PURPLE marker
      setTimeout(() => {
        const mapTab = document.querySelector('[data-tab="tab-stations"]');
        if (mapTab) mapTab.click();
        if (st && STATE.map && st.latitude && st.longitude) {
          STATE.map.setView([st.latitude, st.longitude], 14);
          STATE.map.invalidateSize();
        }
      }, 700);

      loadPaymentHistory();
    } catch (err) {
      console.error('Booking reservation error:', err);
      let errMsg = err.message || '';
      if (errMsg.toLowerCase().includes('out of service')) {
        showAlert(`⚠️ Cannot reserve slot: This charging station is currently Out of Service for maintenance.`, 'error');
      } else {
        showAlert(`Booking failed: ${errMsg}`, 'error');
      }
      DOM.bookingConfirmationBox?.classList.add('hidden');
    }
  }


  // --------------------------------------------------------------------------
  // Billing & Invoices Module
  // --------------------------------------------------------------------------
  async function downloadInvoice() {
    if (!requireAuth('download an invoice')) return;

    const bookingId = DOM.invoiceBookingId.value;
    if (!bookingId) {
      showAlert('Enter a booking ID to download invoice.', 'error');
      return;
    }

    DOM.invoiceDownloadStatus.innerHTML = '<span style="color: #94a3b8; font-size: 12px;">Generating PDF invoice...</span>';

    try {
      const blob = await apiRequest(`/billing/bookings/${bookingId}/invoice`);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `chargeslot-invoice-${bookingId}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      DOM.invoiceDownloadStatus.innerHTML = '<span style="color: #10b981; font-size: 12px;">Invoice downloaded successfully!</span>';
    } catch (err) {
      DOM.invoiceDownloadStatus.innerHTML = `<span style="color: #ef4444; font-size: 12px;">Download error: ${err.message}</span>`;
    }
  }

  async function loadPaymentHistory() {
    try {
      const data = await apiRequest('/payments/history');
      if (!Array.isArray(data) || !data.length) {
        DOM.paymentHistoryTbody.innerHTML = `<tr><td colspan="5" class="text-center">No payment history recorded yet.</td></tr>`;
        return;
      }

      DOM.paymentHistoryTbody.innerHTML = data.map(item => `
        <tr>
          <td>#${item.booking_id || item.id}</td>
          <td>₹${((item.amount_paise || 0) / 100).toFixed(2)}</td>
          <td>${item.payment_type || 'Reservation'}</td>
          <td><span class="tag-badge ${item.status === 'captured' ? 'avail' : ''}">${item.status}</span></td>
          <td>
            ${item.invoice_url ? `<button class="btn btn-primary btn-sm" onclick="window.fetchDirectInvoice(${item.booking_id})" title="Download Tax Invoice PDF">📄 PDF</button>` : `<button class="btn btn-secondary btn-sm" onclick="window.openPaymentModal(${item.booking_id})" title="Complete &amp; Pay">💳 Pay</button>`}
          </td>
        </tr>
      `).join('');
    } catch {
      DOM.paymentHistoryTbody.innerHTML = `<tr><td colspan="5" class="text-center">Sign in as driver to view payment history.</td></tr>`;
    }
  }

  window.fetchDirectInvoice = function (bId) {
    DOM.invoiceBookingId.value = bId;
    downloadInvoice();
  };

  // --------------------------------------------------------------------------
  // Interactive Demo Payment Gateway
  // --------------------------------------------------------------------------
  async function openPaymentModal(bId) {
    if (!requireAuth('access payment')) return;

    const bookingId = bId || parseInt(DOM.invoiceBookingId?.value, 10) || 1;
    STATE.paymentActiveBookingId = bookingId;

    if (DOM.paymentModalBody) DOM.paymentModalBody.classList.remove('hidden');
    if (DOM.paymentModalSuccess) DOM.paymentModalSuccess.classList.add('hidden');
    if (DOM.payModalStatus) DOM.payModalStatus.innerHTML = '';

    if (DOM.payModalBookingId) DOM.payModalBookingId.textContent = `#CS-${String(bookingId).padStart(8, '0')}`;
    if (DOM.payModalStation) DOM.payModalStation.textContent = 'Loading details...';

    DOM.paymentModal?.showModal();

    try {
      const preview = await apiRequest(`/payments/demo/preview/${bookingId}`);
      if (DOM.payModalStation) DOM.payModalStation.textContent = preview.station_name;
      if (DOM.payModalEnergy) DOM.payModalEnergy.textContent = `${preview.est_energy_kwh.toFixed(2)} kWh`;
      if (DOM.payModalEnergyCost) DOM.payModalEnergyCost.textContent = `₹${preview.energy_cost.toFixed(2)} (@ ₹${preview.price_per_kwh}/kWh)`;
      if (DOM.payModalTax) DOM.payModalTax.textContent = `₹${preview.tax_amount.toFixed(2)}`;
      if (DOM.payModalTotal) DOM.payModalTotal.textContent = `₹${preview.total_amount.toFixed(2)}`;
      if (DOM.btnSubmitPayment) {
        DOM.btnSubmitPayment.textContent = `Pay ₹${preview.total_amount.toFixed(2)} Now`;
        DOM.btnSubmitPayment.disabled = false;
      }
    } catch {
      if (DOM.payModalStation) DOM.payModalStation.textContent = 'ChargeSlot Hub';
      if (DOM.payModalEnergy) DOM.payModalEnergy.textContent = '22.50 kWh';
      if (DOM.payModalEnergyCost) DOM.payModalEnergyCost.textContent = '₹337.50';
      if (DOM.payModalTax) DOM.payModalTax.textContent = '₹16.88';
      if (DOM.payModalTotal) DOM.payModalTotal.textContent = '₹354.38';
      if (DOM.btnSubmitPayment) {
        DOM.btnSubmitPayment.textContent = 'Pay ₹354.38 Now';
        DOM.btnSubmitPayment.disabled = false;
      }
    }
  }

  async function submitDemoPayment() {
    const bookingId = STATE.paymentActiveBookingId || parseInt(DOM.invoiceBookingId?.value, 10) || 1;
    const selectedMethodInput = document.querySelector('input[name="demo-pay-method"]:checked');
    const paymentMethod = selectedMethodInput ? selectedMethodInput.value : 'upi';

    if (DOM.payModalStatus) {
      DOM.payModalStatus.innerHTML = '<div style="color: #38bdf8; font-size: 0.85rem; text-align: center; padding: 0.5rem;"><span class="status-pulse" style="background:#38bdf8; display:inline-block; margin-right:6px;"></span> Authorizing payment with gateway...</div>';
    }
    if (DOM.btnSubmitPayment) DOM.btnSubmitPayment.disabled = true;

    try {
      // Simulate slight realistic gateway processing delay
      await new Promise(r => setTimeout(r, 600));

      const res = await apiRequest('/payments/demo/complete-and-pay', {
        method: 'POST',
        body: JSON.stringify({
          booking_id: bookingId,
          payment_method: paymentMethod,
        }),
      });

      if (DOM.paymentModalBody) DOM.paymentModalBody.classList.add('hidden');
      if (DOM.paymentModalSuccess) DOM.paymentModalSuccess.classList.remove('hidden');
      if (DOM.payModalTxnId) DOM.payModalTxnId.textContent = `Txn ID: ${res.transaction_id || 'CS-PAY-SUCCESS'}`;

      // Refresh payment history table and pre-fill invoice input
      if (DOM.invoiceBookingId) DOM.invoiceBookingId.value = bookingId;
      loadPaymentHistory();

      // Clear active reservation for this booking/station so dot returns to Available (GREEN)
      for (const [stIdStr, resv] of Object.entries(STATE.activeReservations)) {
        if (resv.bookingId === bookingId || parseInt(stIdStr, 10) === STATE.selectedStation?.id) {
          const stId = parseInt(stIdStr, 10);
          delete STATE.activeReservations[stIdStr];
          STATE.reservedStationIds.delete(stId);
          const st = STATE.stations.find(s => s.id === stId);
          if (st && st.color_code !== 'red') {
            st.color_code = 'green';
            st.status_label = 'Available';
            st.badge_text = 'Available';
          }
        }
      }
      saveActiveReservations();
      renderStationMarkers(STATE.stations);
      renderStationsList(STATE.stations);

      showAlert(`🎉 Payment captured! ₹${res.amount_inr.toFixed(2)} received via ${paymentMethod.toUpperCase()}. Session completed and station is now Available (GREEN). Tax Invoice is ready.`, 'info');
    } catch (err) {
      if (DOM.payModalStatus) {
        DOM.payModalStatus.innerHTML = `<div style="color: #ef4444; font-size: 0.85rem; text-align: center;">Payment error: ${escapeHtml(err.message)}</div>`;
      }
      if (DOM.btnSubmitPayment) DOM.btnSubmitPayment.disabled = false;
    }
  }

  window.openPaymentModal = openPaymentModal;

  // --------------------------------------------------------------------------
  // Profile & Settings Module
  // --------------------------------------------------------------------------
  async function loadProfile() {
    if (!STATE.token) {
      if (DOM.profileGuestView) DOM.profileGuestView.classList.remove('hidden');
      if (DOM.profileAuthView) DOM.profileAuthView.classList.add('hidden');
      return;
    }

    if (DOM.profileGuestView) DOM.profileGuestView.classList.add('hidden');
    if (DOM.profileAuthView) DOM.profileAuthView.classList.remove('hidden');

    try {
      const p = await apiRequest('/accounts/profile');
      if (DOM.profileDisplayName) DOM.profileDisplayName.textContent = p.name || 'User';
      if (DOM.profileDisplayEmail) DOM.profileDisplayEmail.textContent = p.email || '';
      if (DOM.profileDisplayRole) DOM.profileDisplayRole.textContent = p.role || 'DRIVER';
      if (DOM.profileAvatar) DOM.profileAvatar.textContent = (p.name || p.email || 'U')[0].toUpperCase();
      if (DOM.profileCreatedDate && p.created_at) {
        DOM.profileCreatedDate.textContent = new Date(p.created_at).toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' });
      }

      if (DOM.profileInputName) DOM.profileInputName.value = p.name || '';
      if (DOM.profileInputPhone) DOM.profileInputPhone.value = p.phone || '';
      if (DOM.profileChargingMode) DOM.profileChargingMode.value = p.default_charging_mode || 'Fastest';

      if (DOM.profileTargetBattery) {
        DOM.profileTargetBattery.value = p.default_target_battery || 80;
        if (DOM.profileTargetBatteryDisplay) DOM.profileTargetBatteryDisplay.textContent = `${p.default_target_battery || 80}%`;
      }

      if (DOM.profileLowBattery) {
        DOM.profileLowBattery.value = p.low_battery_threshold || 20;
        if (DOM.profileLowBatteryDisplay) DOM.profileLowBatteryDisplay.textContent = `${p.low_battery_threshold || 20}%`;
      }

      if (DOM.profileSearchRadius) {
        DOM.profileSearchRadius.value = p.default_search_radius || 25;
        if (DOM.profileSearchRadiusDisplay) DOM.profileSearchRadiusDisplay.textContent = `${p.default_search_radius || 25} km`;
      }

      if (DOM.profileNotifyEmail) DOM.profileNotifyEmail.checked = !!p.notify_email;
      if (DOM.profileNotifySms) DOM.profileNotifySms.checked = !!p.notify_sms;
      if (DOM.profileNotifyPush) DOM.profileNotifyPush.checked = !!p.notify_push;
    } catch (err) {
      console.error('Failed to load profile:', err);
    }
  }

  async function handleSaveProfile(e) {
    e.preventDefault();
    if (!requireAuth('save profile')) return;

    const name = DOM.profileInputName?.value.trim();
    const phone = DOM.profileInputPhone?.value.trim();
    const default_charging_mode = DOM.profileChargingMode?.value || 'Fastest';
    const default_target_battery = parseInt(DOM.profileTargetBattery?.value, 10) || 80;
    const low_battery_threshold = parseInt(DOM.profileLowBattery?.value, 10) || 20;
    const default_search_radius = parseInt(DOM.profileSearchRadius?.value, 10) || 25;
    const notify_email = !!DOM.profileNotifyEmail?.checked;
    const notify_sms = !!DOM.profileNotifySms?.checked;
    const notify_push = !!DOM.profileNotifyPush?.checked;

    if (DOM.profileSaveStatus) {
      DOM.profileSaveStatus.innerHTML = '<span style="color: #38bdf8; font-size: 0.85rem;">Saving preferences...</span>';
    }

    try {
      const updated = await apiRequest('/accounts/edit-profile-and-preferences', {
        method: 'PATCH',
        body: JSON.stringify({
          name,
          phone,
          default_charging_mode,
          default_target_battery,
          low_battery_threshold,
          default_search_radius,
          notify_email,
          notify_sms,
          notify_push,
        }),
      });

      if (DOM.profileSaveStatus) {
        DOM.profileSaveStatus.innerHTML = '<span style="color: #10b981; font-size: 0.85rem; font-weight: 600;">✓ Profile and charging preferences saved successfully!</span>';
        setTimeout(() => { if (DOM.profileSaveStatus) DOM.profileSaveStatus.innerHTML = ''; }, 3500);
      }

      STATE.user.name = updated.name;
      localStorage.setItem('chargeslot_user', JSON.stringify(STATE.user));
      updateUserUI();
      showAlert('Profile and preferences updated successfully!', 'info');
    } catch (err) {
      if (DOM.profileSaveStatus) {
        DOM.profileSaveStatus.innerHTML = `<span style="color: #ef4444; font-size: 0.85rem;">Error: ${escapeHtml(err.message)}</span>`;
      }
    }
  }

  async function handleChangePassword(e) {
    e.preventDefault();
    if (!requireAuth('change password')) return;

    const current_password = DOM.pwdCurrent?.value;
    const new_password = DOM.pwdNew?.value;
    const confirm_password = DOM.pwdConfirm?.value;

    if (!current_password || !new_password) {
      if (DOM.pwdChangeStatus) {
        DOM.pwdChangeStatus.innerHTML = '<span style="color: #ef4444; font-size: 0.85rem;">Current and new password are required.</span>';
      }
      return;
    }

    if (new_password !== confirm_password) {
      if (DOM.pwdChangeStatus) {
        DOM.pwdChangeStatus.innerHTML = '<span style="color: #ef4444; font-size: 0.85rem;">New passwords do not match. Please verify.</span>';
      }
      return;
    }

    if (DOM.pwdChangeStatus) {
      DOM.pwdChangeStatus.innerHTML = '<span style="color: #38bdf8; font-size: 0.85rem;">Verifying and updating password...</span>';
    }

    try {
      await apiRequest('/accounts/change-password', {
        method: 'POST',
        body: JSON.stringify({ current_password, new_password }),
      });

      if (DOM.pwdCurrent) DOM.pwdCurrent.value = '';
      if (DOM.pwdNew) DOM.pwdNew.value = '';
      if (DOM.pwdConfirm) DOM.pwdConfirm.value = '';

      if (DOM.pwdChangeStatus) {
        DOM.pwdChangeStatus.innerHTML = '<span style="color: #10b981; font-size: 0.85rem; font-weight: 600;">✓ Password updated successfully!</span>';
        setTimeout(() => { if (DOM.pwdChangeStatus) DOM.pwdChangeStatus.innerHTML = ''; }, 4000);
      }

      showAlert('Password updated successfully!', 'info');
    } catch (err) {
      if (DOM.pwdChangeStatus) {
        DOM.pwdChangeStatus.innerHTML = `<span style="color: #ef4444; font-size: 0.85rem;">Failed: ${escapeHtml(err.message)}</span>`;
      }
    }
  }

  // --------------------------------------------------------------------------
  // Authentication & Session
  // --------------------------------------------------------------------------
  async function performLogin(identifier, password) {
    try {
      const data = await apiRequest('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ identifier, password }),
      });

      STATE.token = data.access_token;
      STATE.user = { email: identifier, role: data.role || 'driver' };
      localStorage.setItem('chargeslot_token', STATE.token);
      localStorage.setItem('chargeslot_user', JSON.stringify(STATE.user));

      updateUserUI();
      return true;
    } catch (err) {
      console.warn('Login attempt failed:', err);
      return false;
    }
  }

  function requireAuth(action = 'proceed') {
    if (STATE.token) return true;
    showAlert(`Please sign in first to ${action}.`, 'error');
    DOM.authModal?.showModal();
    return false;
  }

  window.fillDemoCredentials = function (email, password) {
    const emailInput = document.getElementById('signin-email');
    const pwdInput = document.getElementById('signin-password');
    if (emailInput) emailInput.value = email;
    if (pwdInput) pwdInput.value = password;
  };

  async function handleSignUp(e) {
    e.preventDefault();
    const name = document.getElementById('signup-name')?.value.trim();
    const email = document.getElementById('signup-email')?.value.trim();
    const phone = document.getElementById('signup-phone')?.value.trim();
    const password = document.getElementById('signup-password')?.value;

    if (!name || !email || !phone || !password) {
      showAlert('All registration fields are required.', 'error');
      return;
    }

    try {
      await apiRequest('/auth/register', {
        method: 'POST',
        body: JSON.stringify({ name, email, phone, password }),
      });

      showAlert('Registration successful! Signing in...', 'info');
      const ok = await performLogin(email, password);
      if (ok) {
        DOM.authModal?.close();
        await loadStations();
        loadPaymentHistory();
      }
    } catch (err) {
      showAlert(`Registration failed: ${escapeHtml(err.message)}`, 'error');
    }
  }

  window.quickDemoLogin = async function (email = '1234@gmail.com', password = 'Password@123') {
    const ok = await performLogin(email, password);
    if (ok) {
      DOM.authModal?.close();
      showAlert(`Signed in as ${email}`, 'info');
      await loadStations();
      loadPaymentHistory();
    } else {
      showAlert('Sign In Failed. Please verify credentials.', 'error');
    }
  };

  async function handleSignIn(e) {
    e.preventDefault();
    const email = document.getElementById('signin-email').value.trim();
    const password = document.getElementById('signin-password').value;

    const ok = await performLogin(email, password);
    if (ok) {
      DOM.authModal.close();
      showAlert('Signed in successfully!', 'info');
      await loadStations();
      loadPaymentHistory();
    } else {
      showAlert('Sign In Failed: Invalid identifier or password.', 'error');
    }
  }

  function logoutUser() {
    STATE.token = null;
    STATE.user = null;
    localStorage.removeItem('chargeslot_token');
    localStorage.removeItem('chargeslot_user');
    updateUserUI();
    showAlert('Signed out. Switched to guest view.', 'info');
    loadStations();
  }

  async function loadUserVehicles() {
    if (!STATE.token || !DOM.batteryVehicleSelect) return;

    try {
      const data = await apiRequest('/vehicles');
      const list = data.items || data.vehicles || data || [];
      if (Array.isArray(list) && list.length > 0) {
        DOM.batteryVehicleSelect.innerHTML = list.map(v => {
          VEHICLES[String(v.id)] = {
            name: `${v.make} ${v.model}`,
            capacity: v.battery_kwh || 40.5,
            consumption: v.consumption_kwh_100km || 15.0,
          };
          return `<option value="${v.id}" ${v.is_default ? 'selected' : ''}>
            ${escapeHtml(v.make)} ${escapeHtml(v.model)} (${v.battery_kwh} kWh, ${v.consumption_kwh_100km || 15.0} kWh/100km)
          </option>`;
        }).join('');

        const defaultVehicle = list.find(v => v.is_default) || list[0];
        if (defaultVehicle) {
          DOM.batteryVehicleSelect.value = defaultVehicle.id;
        }
        calculateBatteryEstimates();
      }
    } catch {
      // Keep static defaults if vehicles couldn't be loaded
    }
  }

  function updateUserUI() {
    if (STATE.user && STATE.token) {
      DOM.currentUserBadge.textContent = `${STATE.user.role}: ${STATE.user.email.split('@')[0]}`;
      DOM.btnAuthModal.classList.add('hidden');
      DOM.btnLogout.classList.remove('hidden');
      loadUserVehicles();
    } else {
      DOM.currentUserBadge.textContent = 'Guest Mode';
      DOM.btnAuthModal.classList.remove('hidden');
      DOM.btnLogout.classList.add('hidden');
    }
    loadProfile();
  }

  // --------------------------------------------------------------------------
  // Event Bindings & Bootstrap
  // --------------------------------------------------------------------------
  function setupEvents() {
    // Navigation Tabs
    DOM.navTabs.forEach(tab => {
      tab.addEventListener('click', () => {
        DOM.navTabs.forEach(t => t.classList.remove('active'));
        DOM.tabContents.forEach(c => c.classList.remove('active'));

        tab.classList.add('active');
        const targetTab = document.getElementById(tab.dataset.tab);
        if (targetTab) targetTab.classList.add('active');

        if (tab.dataset.tab === 'tab-stations' && STATE.map) {
          setTimeout(() => STATE.map.invalidateSize(), 150);
        }
        if (tab.dataset.tab === 'tab-profile') {
          loadProfile();
        }
        if (tab.dataset.tab === 'tab-booking') {
          loadUserVehicles();
        }
      });
    });

    // Alert Close
    DOM.btnCloseAlert?.addEventListener('click', () => DOM.globalAlert.classList.add('hidden'));

    // Auth Modal
    DOM.btnAuthModal?.addEventListener('click', () => DOM.authModal.showModal());
    DOM.btnCloseAuthModal?.addEventListener('click', () => DOM.authModal.close());
    DOM.btnLogout?.addEventListener('click', logoutUser);
    DOM.formSignin?.addEventListener('submit', handleSignIn);
    DOM.formSignup?.addEventListener('submit', handleSignUp);

    DOM.tabBtnSignin?.addEventListener('click', () => {
      DOM.tabBtnSignin.classList.add('active');
      DOM.tabBtnSignup.classList.remove('active');
      DOM.formSignin.classList.remove('hidden');
      DOM.formSignup.classList.add('hidden');
    });

    DOM.tabBtnSignup?.addEventListener('click', () => {
      DOM.tabBtnSignup.classList.add('active');
      DOM.tabBtnSignin.classList.remove('active');
      DOM.formSignup.classList.remove('hidden');
      DOM.formSignin.classList.add('hidden');
    });

    // Search & Filter
    const triggerSearch = () => {
      const q = DOM.searchInput?.value.trim().toLowerCase() || '';
      if (!q) {
        renderStationsList(STATE.stations);
        renderStationMarkers(STATE.stations);
        return;
      }
      const filtered = STATE.stations.filter(s =>
        s.name.toLowerCase().includes(q) || s.address.toLowerCase().includes(q)
      );
      renderStationsList(filtered);
      renderStationMarkers(filtered);
    };

    DOM.btnSearchStations?.addEventListener('click', triggerSearch);
    DOM.searchInput?.addEventListener('keyup', (e) => {
      if (e.key === 'Enter') triggerSearch();
    });

    DOM.btnCenterUserLocation?.addEventListener('click', () => {
      if (STATE.map) {
        STATE.map.setView([STATE.currentLocation.lat, STATE.currentLocation.lon], 13);
        STATE.map.invalidateSize();
      }
    });

    DOM.filterRadius?.addEventListener('input', (e) => {
      DOM.radiusDisplay.textContent = `${e.target.value} km`;
    });

    DOM.btnApplyFilters?.addEventListener('click', loadStations);
    DOM.btnResetFilters?.addEventListener('click', () => {
      DOM.searchInput.value = '';
      DOM.filterConnector.value = '';
      DOM.filterMinPower.value = '';
      DOM.filterRadius.value = 25;
      DOM.radiusDisplay.textContent = '25 km';
      DOM.filterAvailableNow.checked = false;
      loadStations();
    });

    // Route Preview
    DOM.btnCalculateRoute?.addEventListener('click', calculateRoutePreview);

    // Battery Estimators
    DOM.batteryVehicleSelect?.addEventListener('change', calculateBatteryEstimates);
    DOM.batterySocSlider?.addEventListener('input', calculateBatteryEstimates);
    DOM.batteryTargetSoc?.addEventListener('input', calculateBatteryEstimates);
    DOM.bookingStationSelect?.addEventListener('change', () => {
      calculateBatteryEstimates();
      renderSlotTimeline();
    });

    // Slot Booking
    DOM.slotDatePicker?.addEventListener('change', renderSlotTimeline);
    DOM.btnConfirmSlotClaim?.addEventListener('click', confirmSlotClaim);

    // Billing & Demo Payment
    DOM.btnDownloadInvoice?.addEventListener('click', downloadInvoice);
    DOM.btnOpenPaymentModal?.addEventListener('click', () => openPaymentModal());
    DOM.btnClosePaymentModal?.addEventListener('click', () => DOM.paymentModal?.close());
    DOM.btnSubmitPayment?.addEventListener('click', submitDemoPayment);
    DOM.btnPayModalDone?.addEventListener('click', () => DOM.paymentModal?.close());
    DOM.btnPayModalDownloadInvoice?.addEventListener('click', () => {
      DOM.paymentModal?.close();
      const bId = STATE.paymentActiveBookingId || parseInt(DOM.invoiceBookingId?.value, 10) || 1;
      if (DOM.invoiceBookingId) DOM.invoiceBookingId.value = bId;
      downloadInvoice();
    });

    // Profile & Preferences
    DOM.profileTargetBattery?.addEventListener('input', e => {
      if (DOM.profileTargetBatteryDisplay) DOM.profileTargetBatteryDisplay.textContent = e.target.value + '%';
    });
    DOM.profileLowBattery?.addEventListener('input', e => {
      if (DOM.profileLowBatteryDisplay) DOM.profileLowBatteryDisplay.textContent = e.target.value + '%';
    });
    DOM.profileSearchRadius?.addEventListener('input', e => {
      if (DOM.profileSearchRadiusDisplay) DOM.profileSearchRadiusDisplay.textContent = e.target.value + ' km';
    });
    DOM.formEditProfile?.addEventListener('submit', handleSaveProfile);
    DOM.formChangePassword?.addEventListener('submit', handleChangePassword);
    DOM.btnProfileGuestSignin?.addEventListener('click', () => DOM.authModal?.showModal());
    DOM.btnProfileLogoutCard?.addEventListener('click', logoutUser);
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/[&<>"']/g, m => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[m]);
  }

  // --------------------------------------------------------------------------
  // Application Bootstrap
  // --------------------------------------------------------------------------
  document.addEventListener('DOMContentLoaded', () => {
    // Set default date for slot timeline to today
    const today = new Date().toISOString().split('T')[0];
    if (DOM.slotDatePicker) DOM.slotDatePicker.value = today;

    loadActiveReservations();
    setInterval(checkAndExpireReservations, 5000);

    updateUserUI();
    initMap();
    loadStations();
    calculateBatteryEstimates();
    renderSlotTimeline();
    loadPaymentHistory();
    setupEvents();
  });

})();

