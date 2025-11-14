/* main scripts consolidated: progress bars, login toggle, sidebar preservation, animated title */
document.addEventListener('DOMContentLoaded', function () {
    // --- Progress bars (statistiques) ---
    setTimeout(() => {
        document.querySelectorAll('.progress-bar').forEach(bar => {
            const percentage = bar.getAttribute('data-percentage');
            if (percentage !== null) {
                bar.style.width = percentage + '%';
            }
        });
    }, 200);

    // --- Toggle password visibility (login) ---
    const togglePassword = document.getElementById('togglePassword');
    if (togglePassword) {
        togglePassword.addEventListener('click', function () {
            const passwordInput = document.getElementById('password');
            const icon = this.querySelector('i');
            if (passwordInput && icon) {
                if (passwordInput.type === 'password') {
                    passwordInput.type = 'text';
                    icon.classList.replace('ri-eye-line', 'ri-eye-off-line');
                } else {
                    passwordInput.type = 'password';
                    icon.classList.replace('ri-eye-off-line', 'ri-eye-line');
                }
            }
        });
    }

    // --- Prevent sidebar disappearing when clicking navbar links ---
    const sidebar = document.querySelector('.sidebar');
    const navbar = document.querySelector('.navbar');
    if (sidebar && navbar) {
        // When any navbar link or dropdown item is clicked, ensure the sidebar remains visible.
        const navSelectors = '.navbar-nav .nav-link, .dropdown-item, .nav-link';
        navbar.querySelectorAll(navSelectors).forEach(link => {
            link.addEventListener('click', function () {
                // Do not prevent navigation. Just restore sidebar visibility/state.
                sidebar.style.display = 'block';
                sidebar.style.visibility = 'visible';
                document.body.classList.add('has-sidebar');
            });
        });

        // Also ensure clicks on the navbar container don't toggle sidebar off accidentally
        navbar.addEventListener('click', function () {
            sidebar.style.display = 'block';
            sidebar.style.visibility = 'visible';
            document.body.classList.add('has-sidebar');
        });
    }

    // --- Animated hero title (phrases rotate) ---
    const animated = document.getElementById('animated-title');
    if (animated) {
        const raw = (animated.getAttribute('data-phrases') || 'BibliosDjib').trim();
        const phrases = raw.split('|').map(s => s.trim()).filter(Boolean);
        if (phrases.length > 0) {
            let idx = 0;
            animated.textContent = phrases[0];
            animated.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
            animated.style.display = 'inline-block';
            animated.style.opacity = '1';

            const showNext = () => {
                animated.style.opacity = '0';
                animated.style.transform = 'translateY(-6px)';
                setTimeout(() => {
                    idx = (idx + 1) % phrases.length;
                    animated.textContent = phrases[idx];
                    animated.style.opacity = '1';
                    animated.style.transform = 'translateY(0)';
                }, 400);
            };
            // rotate every 3 seconds
            setInterval(showNext, 2000);
        }
    }
});