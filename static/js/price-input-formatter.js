/**
 * Global Price Input Formatter
 * Formats all price inputs with RTL direction and 2 decimal places
 * Works across all pages in the system
 */

(function() {
    'use strict';

    // Configuration
    const DECIMAL_PLACES = 2;
    const DECIMAL_SEPARATOR = '.';
    const THOUSANDS_SEPARATOR = ',';

    /**
     * Format a number to 2 decimal places
     */
    function formatPrice(value) {
        if (!value || value === '' || value === null || value === undefined) {
            return '0.00';
        }

        // Convert to number
        let num = parseFloat(value);
        if (isNaN(num)) {
            return '0.00';
        }

        // Round to 2 decimal places
        num = Math.round(num * 100) / 100;

        // Format with 2 decimal places
        return num.toFixed(DECIMAL_PLACES);
    }

    /**
     * Parse input value to number
     */
    function parsePriceValue(value) {
        if (!value || value === '') {
            return 0;
        }

        // Remove any formatting (commas, spaces)
        let cleaned = value.toString().replace(/,/g, '').replace(/\s/g, '').trim();

        // Handle comma as decimal separator if present
        if (cleaned.includes(',')) {
            cleaned = cleaned.replace(',', '.');
        }

        const num = parseFloat(cleaned);
        return isNaN(num) ? 0 : num;
    }

    /**
     * Format input value on blur - preserve user's input exactly, only minimal formatting if needed
     */
    function handleBlur(event) {
        const input = event.target;
        let value = input.value;
        
        // If empty, leave it empty
        if (!value || value.trim() === '' || value === '0' || value === '0.00') {
            input.value = '';
            return;
        }
        
        // Clean the value - remove any invalid characters but preserve the structure
        value = value.trim();
        
        // Store original value to compare later
        const originalValue = value;
        
        // Check if value already has decimal point with 2 decimal places
        if (value.includes('.')) {
            const parts = value.split('.');
            if (parts.length === 2) {
                // Value already has decimal point
                // Only pad if less than 2 decimal places, otherwise preserve exactly
                if (parts[1].length === DECIMAL_PLACES) {
                    // Already has 2 decimal places - preserve exactly as typed, don't change anything
                    // Don't set input.value again to avoid triggering events
                    return;
                } else if (parts[1].length < DECIMAL_PLACES) {
                    // Less than 2 decimal places - pad with zeros
                    parts[1] = parts[1].padEnd(DECIMAL_PLACES, '0');
                    value = parts[0] + '.' + parts[1];
                    // Only update if different
                    if (value !== originalValue) {
                        input.value = value;
                    }
                } else {
                    // More than 2 decimal places - truncate to 2 (preserve what user typed, just limit precision)
                    parts[1] = parts[1].substring(0, DECIMAL_PLACES);
                    value = parts[0] + '.' + parts[1];
                    // Only update if different
                    if (value !== originalValue) {
                        input.value = value;
                    }
                }
            } else {
                // Multiple decimal points - this shouldn't happen, but handle it
                const numValue = parsePriceValue(value);
                if (numValue !== 0) {
                    const formatted = formatPrice(numValue);
                    if (formatted !== originalValue) {
                        input.value = formatted;
                    }
                } else {
                    input.value = '';
                }
            }
        } else {
            // No decimal point - check if it's a valid number
            const numValue = parsePriceValue(value);
            if (numValue !== 0) {
                // Add .00 to whole numbers
                const formatted = formatPrice(numValue);
                if (formatted !== originalValue) {
                    input.value = formatted;
                }
            } else {
                // Zero value - leave empty
                input.value = '';
                return;
            }
        }
        
        // Don't trigger input event - it can cause the calculator-style handler to run again
        // Other scripts should listen to blur or change events if they need to react
    }
    
    /**
     * Handle input event - calculator-style input where typed digit appears as second decimal
     */
    function handleInput(event) {
        const input = event.target;
        let value = input.value;

        // Handle backspace/delete - allow normal deletion
        if (event.inputType === 'deleteContentBackward' || 
            event.inputType === 'deleteContentForward' ||
            event.key === 'Backspace' || 
            event.key === 'Delete') {
            // Allow normal deletion, format on blur
            return;
        }

        // Get the last character typed (if it's a digit)
        const lastChar = value.charAt(value.length - 1);
        
        // Only process if a digit was typed
        if (/\d/.test(lastChar)) {
            // Remove the last character temporarily to get the base value
            const baseValue = value.slice(0, -1);
            
            // Parse current value (without the last digit)
            // If empty, start from 0
            let currentNum = parsePriceValue(baseValue || '');
            
            // Convert to integer (multiply by 100 to work with cents)
            let cents = Math.round(currentNum * 100);
            
            // Shift left and add new digit (calculator-style)
            cents = cents * 10;
            cents = cents + parseInt(lastChar);
            
            // Convert back to decimal
            currentNum = cents / 100;
            
            // Format with 2 decimal places
            value = formatPrice(currentNum);
            
            input.value = value;
            
            // Position cursor at end (after second decimal digit)
            setTimeout(() => {
                try {
                    const cursorPosition = value.length;
                    input.setSelectionRange(cursorPosition, cursorPosition);
                } catch (e) {
                    // Ignore if fails
                }
            }, 0);
            
            // Prevent default to avoid duplicate input
            if (event.key) {
                event.preventDefault();
            }
            return;
        }

        // Handle decimal point or comma - allow if not already present
        if (lastChar === '.' || lastChar === ',') {
            if (!value.includes('.') && !value.slice(0, -1).includes('.')) {
                value = value.replace(',', '.');
                // If no digits before decimal, add 0
                if (value.startsWith('.')) {
                    value = '0' + value;
                }
                input.value = value;
            } else {
                // Remove duplicate decimal point
                value = value.slice(0, -1);
                input.value = value;
            }
            return;
        }

        // Remove any other invalid characters
        value = value.replace(/[^\d.,]/g, '');
        if (input.value !== value) {
            input.value = value;
        }
    }

    /**
     * Handle focus - position cursor 2 digits after decimal point (at far right)
     */
    function handleFocus(event) {
        const input = event.target;
        // Use multiple timing methods to ensure cursor positioning works
        setTimeout(() => {
            let value = input.value || '';
            
            // Only format if there's a value, otherwise leave empty
            if (value && value !== '' && value !== '0' && value !== '0.00') {
                // Ensure value has decimal format
                if (!value.includes('.')) {
                    value = formatPrice(parsePriceValue(value));
                    input.value = value;
                }
                
                // Position cursor 2 digits after decimal point (at the end)
                // This ensures the latest digit appears at the far right
                const cursorPosition = value.length;
                try {
                    input.setSelectionRange(cursorPosition, cursorPosition);
                } catch (e) {
                    // Fallback
                    requestAnimationFrame(() => {
                        try {
                            input.setSelectionRange(cursorPosition, cursorPosition);
                        } catch (e2) {
                            // Ignore if still fails
                        }
                    });
                }
            } else {
                // Empty input - position cursor at start (left side for RTL)
                try {
                    input.setSelectionRange(0, 0);
                } catch (e) {
                    // Ignore
                }
            }
        }, 10);
        
        // Also try after a longer delay to handle any async updates
        setTimeout(() => {
            const value = input.value || '';
            try {
                if (value && value !== '' && value !== '0' && value !== '0.00') {
                    input.setSelectionRange(value.length, value.length);
                } else {
                    input.setSelectionRange(0, 0);
                }
            } catch (e) {
                // Ignore
            }
        }, 50);
    }

    /**
     * Initialize price input formatting for a specific input
     */
    function initializePriceInput(input) {
        if (!input || input.dataset.priceFormatted === 'true') {
            return; // Already initialized
        }

        // Mark as initialized
        input.dataset.priceFormatted = 'true';

        // Apply RTL direction
        input.style.direction = 'rtl';
        input.style.textAlign = 'right';

        // Format initial value only if it has a value, otherwise leave empty
        if (input.value && input.value !== '' && input.value !== '0' && input.value !== '0.00') {
            const value = parsePriceValue(input.value);
            input.value = formatPrice(value);
        } else {
            // Leave empty - don't set to 0.00
            input.value = '';
        }

        // Add event listeners
        input.addEventListener('blur', handleBlur);
        input.addEventListener('input', handleInput);
        input.addEventListener('focus', handleFocus);
        
        // Also handle click to position cursor at end
        input.addEventListener('click', function() {
            setTimeout(() => {
                const value = input.value || '';
                try {
                    if (value && value !== '' && value !== '0' && value !== '0.00') {
                        input.setSelectionRange(value.length, value.length);
                    } else {
                        input.setSelectionRange(0, 0);
                    }
                } catch (e) {
                    // Ignore
                }
            }, 0);
        });

        // Format on paste
        input.addEventListener('paste', function(e) {
            e.preventDefault();
            const pasted = (e.clipboardData || window.clipboardData).getData('text');
            const value = parsePriceValue(pasted);
            input.value = formatPrice(value);
            input.dispatchEvent(new Event('input', { bubbles: true }));
        });
    }

    /**
     * Find and initialize all price inputs on the page
     */
    function initializeAllPriceInputs() {
        // Find inputs by step attribute (0.01 indicates price/money)
        const stepInputs = document.querySelectorAll('input[type="number"][step="0.01"], input[type="number"][step="0.01"]');
        stepInputs.forEach(initializePriceInput);

        // Find inputs by ID patterns
        const priceIds = [
            'prod-price', 'prod-cost',
            'pay-cash', 'pay-mobile', 'pay-card', 'pay-credit',
            'withdrawal-amount', 'new-layby-initial-payment', 'layby-amount-paid',
            'pay-amount', 'ending-cash', 'starting-cash',
            'asset-cost'
        ];
        priceIds.forEach(id => {
            const input = document.getElementById(id);
            if (input) {
                initializePriceInput(input);
            }
        });

        // Find inputs by name patterns
        const priceNames = [
            'prod-price', 'prod-cost',
            'pay-cash', 'pay-mobile', 'pay-card', 'pay-credit',
            'pay_amount', 'new-layby-initial-payment', 'layby-amount-paid'
        ];
        priceNames.forEach(name => {
            const inputs = document.querySelectorAll(`input[name="${name}"]`);
            inputs.forEach(initializePriceInput);
        });

        // Find inputs by class patterns
        const priceClasses = document.querySelectorAll('.price-input, .amount-input, .money-input');
        priceClasses.forEach(initializePriceInput);
    }

    /**
     * Initialize when DOM is ready
     */
    function init() {
        // Initialize immediately if DOM is already loaded
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initializeAllPriceInputs);
        } else {
            initializeAllPriceInputs();
        }

        // Watch for dynamically added inputs
        const observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                mutation.addedNodes.forEach(function(node) {
                    if (node.nodeType === 1) { // Element node
                        // Check if the added node is a price input
                        if (node.tagName === 'INPUT' && 
                            (node.type === 'number' && node.step === '0.01' || 
                             node.id && node.id.match(/(price|cost|amount|payment|withdrawal|cash|mobile|card|credit)/i))) {
                            initializePriceInput(node);
                        }
                        // Check for price inputs within the added node
                        const priceInputs = node.querySelectorAll && node.querySelectorAll('input[type="number"][step="0.01"]');
                        if (priceInputs) {
                            priceInputs.forEach(initializePriceInput);
                        }
                    }
                });
            });
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    }

    // Initialize
    init();

    // Export for manual initialization if needed
    window.priceInputFormatter = {
        initialize: initializeAllPriceInputs,
        format: formatPrice,
        parse: parsePriceValue
    };
})();

