document.addEventListener('DOMContentLoaded', () => {
    const walletInputSection = document.getElementById('wallet-input-section');
    const walletDisplaySection = document.getElementById('wallet-display-section');
    const walletAddressInput = document.getElementById('wallet-address-input');
    const saveWalletBtn = document.getElementById('save-wallet-btn');
    const removeWalletBtn = document.getElementById('remove-wallet-btn');
    const displayedWalletAddress = document.getElementById('displayed-wallet-address');
    const mainContent = document.getElementById('main-content');
    const loadingMessage = document.getElementById('loading-message');
    const errorMessage = document.getElementById('error-message');
    const portfolioSummaryDiv = document.getElementById('portfolio-summary');
    const positionsContainer = document.getElementById('positions-container');

    const WALLET_STORAGE_KEY = 'shadow_cl_wallet_address';

    // Function to show/hide wallet input/display sections
    function updateWalletUI() {
        const storedAddress = localStorage.getItem(WALLET_STORAGE_KEY);
        if (storedAddress) {
            walletInputSection.style.display = 'none';
            walletDisplaySection.style.display = 'block';
            displayedWalletAddress.textContent = formatWalletAddress(storedAddress);
            mainContent.style.display = 'block';
            fetchData(storedAddress);
        } else {
            walletInputSection.style.display = 'block';
            walletDisplaySection.style.display = 'none';
            mainContent.style.display = 'none';
            // Clear previous data if no wallet is set
            portfolioSummaryDiv.innerHTML = '';
            positionsContainer.innerHTML = '';
            errorMessage.textContent = '';
            loadingMessage.style.display = 'none';
        }
    }

    // Function to fetch data from the Python script
    async function fetchData(walletAddress) {
        loadingMessage.textContent = 'Fetching and processing data...';
        loadingMessage.style.display = 'block';
        errorMessage.textContent = '';
        try {
            const response = await fetch(`/api/data?wallet_address=${walletAddress}`);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
            }
            const data = await response.json();
            displayData(data);
        } catch (error) {
            console.error('Error fetching data:', error);
            errorMessage.textContent = `Failed to load data. Error: ${error.message}`;
        } finally {
            loadingMessage.style.display = 'none';
        }
    }

    // Function to display the fetched data
    function displayData(data) {
        if (data.error) {
            errorMessage.textContent = `Error from script: ${data.error}`;
            return;
        }
        if (data.message) {
            positionsContainer.innerHTML = `<p>${data.message}</p>`;
            return;
        }

        portfolioSummaryDiv.innerHTML = `Total Estimated Portfolio Value: ${data.total_portfolio_value} | Found ${data.num_active_positions} active positions.`;
        positionsContainer.innerHTML = ''; // Clear previous content

        data.positions.forEach(position => {
            const card = document.createElement('div');
            card.classList.add('position-card');

            // --- Prepare data for display ---
            const statusClass = position.status === 'IN RANGE' ? 'status-in-range' : 'status-out-of-range';

            // Find xSHADOW rewards for the sub-line
            let xshadowRewardAmount = '';
            if (position.rewards && position.rewards.length > 0) {
                const xshadowReward = position.rewards.find(r => r.symbol === 'xSHADOW');
                if (xshadowReward) {
                    xshadowRewardAmount = `(${xshadowReward.amount} xSHADOW)`;
                }
            }

            // Impermanent Loss & Breakeven
            let ilHtml = '';
            if (position.impermanent_loss_data && Object.keys(position.impermanent_loss_data).length > 0) {
                const ilData = position.impermanent_loss_data;
                const netGainLoss = parseFloat(ilData.current.net_gain_loss.replace(/,/g, ''));
                const netGainLossClass = netGainLoss >= 0 ? 'value-positive' : 'value-negative';

                ilHtml = `
                    <div class="il-analysis">
                        <p class="label">Position Age: <span class="value">${ilData.position_age}</span></p>
                        <hr style="border-color: var(--color-bg-tertiary); margin: 12px 0;">
                        <p class="label"><strong>Current IL:</strong> <span class="value value-negative">${ilData.current.il_usd} (${ilData.current.il_perc})</span></p>
                        <p class="label"><strong>Net Gain/Loss:</strong> <span class="value ${netGainLossClass}">${ilData.current.net_gain_loss}</span></p>
                        <hr style="border-color: var(--color-bg-tertiary); margin: 12px 0;">
                        <p class="label"><strong>At Upper Bound (${ilData.upper_bound.price}):</strong></p>
                        <p>IL: <span class="value value-negative">${ilData.upper_bound.il_usd} (${ilData.upper_bound.il_perc})</span></p>
                        <p>Break Even Time: <span class="value ${getBreakevenColorClass(ilData.upper_bound.breakeven_time_perc)}">${ilData.upper_bound.breakeven_time}</span></p>
                         <p>Fees vs IL: <span class="value">${ilData.upper_bound.fees_vs_il}</span></p>
                        <hr style="border-color: var(--color-bg-tertiary); margin: 12px 0;">
                        <p class="label"><strong>At Lower Bound (${ilData.lower_bound.price}):</strong></p>
                        <p>IL: <span class="value value-negative">${ilData.lower_bound.il_usd} (${ilData.lower_bound.il_perc})</span></p>
                        <p>Break Even Time: <span class="value ${getBreakevenColorClass(ilData.lower_bound.breakeven_time_perc)}">${ilData.lower_bound.breakeven_time}</span></p>
                        <p>Fees vs IL: <span class="value">${ilData.lower_bound.fees_vs_il}</span></p>
                    </div>
                `;
            } else {
                ilHtml = '<p style="color: var(--color-text-secondary);">IL data not available (position may be new).</p>';
            }
            
            const priceRangeHTML = `
                <div class="price-range-visual">
                    <!-- Lower Bound (for desktop view) -->
                    <div class="range-endpoint lower-bound desktop-only">
                        <span class="range-label">${position.price_range_lower}</span>
                        <span class="range-percent">${position.perc_to_lower}</span>
                    </div>

                    <!-- The Bar -->
                    <div class="range-bar">
                        <div class="range-indicator" style="--position: ${position.price_range_percentage}%">
                            <div class="current-price-label">${position.current_price.split(' ')[0]}</div>
                        </div>
                    </div>

                    <!-- Upper Bound (for desktop view) -->
                    <div class="range-endpoint upper-bound desktop-only">
                        <span class="range-label">${position.price_range_upper}</span>
                        <span class="range-percent">${position.perc_to_upper}</span>
                    </div>

                     <!-- Mobile-only labels -->
                    <div class="range-endpoint upper-bound mobile-only">
                        <span class="range-label">${position.price_range_upper}</span>
                        <span class="range-percent">${position.perc_to_upper}</span>
                    </div>
                     <div class="range-endpoint lower-bound mobile-only">
                        <span class="range-label">${position.price_range_lower}</span>
                        <span class="range-percent">${position.perc_to_lower}</span>
                    </div>
                </div>
            `;

            // **UPDATED HTML STRUCTURE FOR THE HEADER**
            card.innerHTML = `
                <div class="card-header">
                    <div class="header-left">
                        <h2>${position.pair}</h2>
                        <div class="status ${statusClass}">${position.status}</div>
                    </div>
                    <div class="header-center">
                        ${priceRangeHTML}
                    </div>
                    <div class="header-right">
                        <div class="position-value">
                            <span style="font-size: 0.7em; color: var(--color-text-secondary);">Est. Value</span><br>
                            ${position.estimated_value_usd}
                        </div>
                    </div>
                </div>

                <div class="card-body">
                    <div class="card-section">
                        <h3 class="section-title">IL & Breakeven Analysis</h3>
                        ${ilHtml}
                    </div>

                    <div class="card-section">
                        <h3 class="section-title">Performance</h3>
                        <div class="metric">
                            <span class="metric-label">Total Rewards</span>
                            <div class="metric-value-container">
                                <span class="metric-value value-positive">${position.total_rewards_usd}</span>
                                <span class="reward-sub-line">${xshadowRewardAmount}</span>
                            </div>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Annualized APR</span>
                            <span class="metric-value value-positive">${position.annualized_apr}</span>
                        </div>
                    </div>
                    <div class="card-section">
                        <h3 class="section-title">Position Details (#${position.token_id})</h3>
                        <div class="metric">
                            <span class="metric-label">Current Price</span>
                            <span class="metric-value-details">${position.current_price}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Initial Price</span>
                            <span class="metric-value-details">${position.initial_state.price}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Current Value</span>
                            <span class="metric-value-details">${position.estimated_value_usd}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Initial Value</span>
                            <span class="metric-value-details">${position.initial_state.usd_value}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Current Balances</span>
                            <span class="metric-value-details">${position.current_balances}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Initial Balances</span>
                            <span class="metric-value-details">${position.initial_state.balances}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Creation Date</span>
                            <span class="metric-value-details">${position.initial_state.date}</span>
                        </div>
                    </div>
                </div>
            `;
            positionsContainer.appendChild(card);
        });
    }

    function getBreakevenColorClass(percentage) {
        if (percentage === -1) return ''; // For 'Met' or N/A
        if (percentage > 75) return 'breakeven-red';
        if (percentage > 40) return 'breakeven-orange';
        if (percentage > 10) return 'breakeven-yellow';
        return 'breakeven-green';
    }

    // Event Listeners
    saveWalletBtn.addEventListener('click', () => {
        const address = walletAddressInput.value.trim();
        if (address) {
            localStorage.setItem(WALLET_STORAGE_KEY, address);
            updateWalletUI();
        } else {
            alert('Please enter a valid wallet address.');
        }
    });

    removeWalletBtn.addEventListener('click', () => {
        localStorage.removeItem(WALLET_STORAGE_KEY);
        updateWalletUI();
    });

    function formatWalletAddress(address) {
        if (address.length <= 10) {
            return address; // Return as is if too short to format
        }
        return `${address.substring(0, 6)}...${address.substring(address.length - 4)}`;
    }

    // Initial UI update on page load
    updateWalletUI();
});
