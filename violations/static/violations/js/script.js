// Global role state used by both login and signup
window.currentRole = window.currentRole || '';

// Toggle password visibility helper (used by inline onclicks)
function togglePasswordVisibility(fieldId) {
    const id = fieldId || 'password';
    const passwordField = document.getElementById(id);
    if (!passwordField) return;

    const passwordGroup = passwordField.closest('.password-group');
    const passwordToggleIcon = passwordGroup ? passwordGroup.querySelector('.password-toggle i') : null;

    if (passwordField.type === 'password') {
        passwordField.type = 'text';
        if (passwordToggleIcon) {
            passwordToggleIcon.classList.remove('fa-eye');
            passwordToggleIcon.classList.add('fa-eye-slash');
        }
    } else {
        passwordField.type = 'password';
        if (passwordToggleIcon) {
            passwordToggleIcon.classList.remove('fa-eye-slash');
            passwordToggleIcon.classList.add('fa-eye');
        }
    }
}

// Role selection shared logic for login and signup
// Debounce rapid role switching and add a slight delayed responsive animation
let roleSwitchLock = false;
function selectRole(role) {
    if (roleSwitchLock || !role) return; // prevent spam clicks
    roleSwitchLock = true;
    window.currentRole = role;

    // Toggle active class on role buttons with a subtle pulse on the selected one
    document.querySelectorAll('.role-btn').forEach(btn => {
        const isActive = btn.dataset.role === role;
        btn.classList.toggle('active', isActive);
        if (isActive) {
            btn.classList.remove('role-pulse');
            void btn.offsetWidth; // restart animation
            btn.classList.add('role-pulse');
        }
    });

    // Show/hide form groups matching role
    document.querySelectorAll('.form-group[data-role]').forEach(group => {
        group.classList.toggle('active', group.dataset.role === role);
    });

    // Animate entire sections if they carry data-role as well
    document.querySelectorAll('.form-section[data-role]').forEach(section => {
        const shouldShow = section.dataset.role === role;
        if (shouldShow) {
            section.classList.add('active');
        } else {
            section.classList.remove('active');
        }
    });

    // Update required attributes for form controls inside role groups
    // Exclude file inputs from being auto-required
    const controls = document.querySelectorAll('.form-group input:not([type="file"]), .form-group select, .form-group textarea');
    controls.forEach(el => {
        const group = el.closest('.form-group');
        if (group && group.dataset && group.dataset.role === role) {
            el.setAttribute('required', 'required');
        } else {
            el.removeAttribute('required');
        }
    });

    // Login-only UI bits
    const signupLink = document.getElementById('signupLink');
    if (signupLink) signupLink.style.display = role === 'student' ? 'block' : 'none';

    const authCta = document.getElementById('authCta');
    if (authCta) authCta.style.display = role === 'student' ? 'block' : 'none';

    // Signup-only: show the terms checkbox if a role is chosen
    const termsCheckbox = document.getElementById('termsCheckbox');
    if (termsCheckbox) termsCheckbox.style.display = role ? 'block' : 'none';

    // Accessibility: move focus to first enabled field in the now-active section
    const activeSection = document.querySelector('.form-section[data-role].active');
    if (activeSection) {
        const firstInput = activeSection.querySelector('input, select, textarea, button');
        if (firstInput) setTimeout(() => firstInput.focus(), 120);
    }

    // Swap left brand image + welcome text (works for both pages)
    const container = document.querySelector('.auth-card');
    const imgStudent = container?.dataset?.roleImgStudent;
    const imgStaff = container?.dataset?.roleImgStaff;
    const imgFaculty = container?.dataset?.roleImgFaculty;

    const brandImg = document.getElementById('roleImage') || document.querySelector('.brand-logo-circle img');
    const welcomeText = document.getElementById('welcomeText') || document.querySelector('.auth-welcome');

    if (brandImg && welcomeText) {
        // Add CSS classes for animation if not present (scoped swap animations)
        brandImg.classList.add('swap-anim-out');
        welcomeText.classList.add('swap-anim-out');
        setTimeout(() => {
            if (role === 'student' && imgStudent) {
                brandImg.src = imgStudent;
                brandImg.alt = 'Student Icon';
                welcomeText.textContent = 'Welcome Student!';
            } else if (role === 'staff' && imgStaff) {
                brandImg.src = imgStaff;
                brandImg.alt = 'Staff Icon';
                welcomeText.textContent = 'Welcome Staff!';
            } else if (role === 'faculty' && imgFaculty) {
                brandImg.src = imgFaculty;
                brandImg.alt = 'Faculty Icon';
                welcomeText.textContent = 'Welcome Faculty!';
            }
            brandImg.classList.remove('swap-anim-out');
            welcomeText.classList.remove('swap-anim-out');
            brandImg.classList.add('swap-anim-in');
            welcomeText.classList.add('swap-anim-in');
            // cleanup after animation ends
            const cleanup = (el) => {
                const endHandler = () => { el.classList.remove('swap-anim-in'); el.removeEventListener('animationend', endHandler); };
                el.addEventListener('animationend', endHandler);
            };
            cleanup(brandImg); cleanup(welcomeText);
            // release lock slightly after animation starts
            setTimeout(() => { roleSwitchLock = false; }, 250);
        }, 140); // slight delay before swap for responsiveness feel
    } else {
        // fallback if elements missing
        roleSwitchLock = false;
    }

    // Reflect role into hidden field for backend submissions
    const roleField = document.getElementById('role_field');
    if (roleField) roleField.value = role;
    const loginRoleField = document.getElementById('login_role_field');
    if (loginRoleField) loginRoleField.value = role;

    // Add a subtle pulse on the auth form when switching roles
    const authFormCard = document.querySelector('.auth-form');
    if (authFormCard) {
        authFormCard.classList.remove('role-pulse');
        // Force reflow to restart animation if already present
        void authFormCard.offsetWidth;
        authFormCard.classList.add('role-pulse');
        // Clean up the class after animation ends
        const removePulse = () => {
            authFormCard.classList.remove('role-pulse');
            authFormCard.removeEventListener('animationend', removePulse);
        };
        authFormCard.addEventListener('animationend', removePulse);
    }

    // Update login form action/mode depending on role
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        const studentAction = loginForm.getAttribute('data-student-action');
        const credentialsAction = loginForm.getAttribute('data-credentials-action');
        if (role === 'student') {
            if (studentAction) loginForm.setAttribute('action', studentAction);
            loginForm.dataset.mode = 'student-backend';
        } else if (role === 'staff' || role === 'faculty') {
            if (credentialsAction) loginForm.setAttribute('action', credentialsAction);
            loginForm.dataset.mode = 'credentials-backend';
        }
    }
    if (!brandImg || !welcomeText) {
        // If animation elements not found, release lock immediately
        roleSwitchLock = false;
    }
}

// Page-specific initialization
document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('loginForm');
    const signupForm = document.getElementById('signupForm');
    const profileBtn = document.getElementById('profileBtn');
    const profileDropdown = document.getElementById('profileDropdown');
    const notifBtn = document.getElementById('notifBtn');
    const notifPanel = document.getElementById('notifPanel');
    const notifClose = document.getElementById('notifClose');

    if (loginForm) {
        // Default role from template hint (if any), else student
        const hintedRole = loginForm.getAttribute('data-default-role');
        if (!window.currentRole) window.currentRole = hintedRole || 'student';
        selectRole(window.currentRole);

        loginForm.addEventListener('submit', (e) => {
            const isStudentBackend = loginForm.dataset.mode === 'student-backend' && window.currentRole === 'student';
            const isCredentialsBackend = loginForm.dataset.mode === 'credentials-backend' && (window.currentRole === 'staff' || window.currentRole === 'faculty');
            const fd = new FormData();
            fd.append('role', window.currentRole);

        

            if (window.currentRole === 'student') {
                fd.append('student_id', document.getElementById('student_id')?.value || '');
                if (isStudentBackend) {
                    // Allow native submit to backend for student login
                    const roleField = document.getElementById('login_role_field');
                    if (roleField) roleField.value = 'student';
                    return; // do not prevent default
                }
            } else if (window.currentRole === 'staff') {
                fd.append('email', document.getElementById('staff_email')?.value || '');
                fd.append('password', document.getElementById('staff_password')?.value || '');
                if (isCredentialsBackend) {
                    const roleField = document.getElementById('login_role_field');
                    if (roleField) roleField.value = 'staff';
                    return; // native submit to backend
                }
            } else if (window.currentRole === 'faculty') {
                // Match Django admin-style field names
                fd.append('username', document.getElementById('faculty_username')?.value || document.getElementById('username')?.value || '');
                fd.append('password', document.getElementById('faculty_password')?.value || '');
                if (isCredentialsBackend) {
                    const roleField = document.getElementById('login_role_field');
                    if (roleField) roleField.value = 'faculty';
                    return; // native submit to backend
                }
            }
            // Frontend-only: no submission; log for visibility
            try { console.log('Login form data:', Object.fromEntries(fd)); } catch {}
            e.preventDefault();
        });
    }

    if (signupForm) {
        // Start with no role selected on signup (UI shows choices)
        // No default select; user picks.

        signupForm.addEventListener('submit', (e) => {
            const isBackend = signupForm.dataset.mode === 'backend';

            if (!window.currentRole) {
                alert('Please select a role');
                e.preventDefault();
                return;
            }

            const terms = document.querySelector('#termsCheckbox input[type="checkbox"]');
            if (terms && !terms.checked) {
                alert('Please accept the terms of agreement');
                e.preventDefault();
                return;
            }

            // For backend mode, let native form submission proceed
            if (isBackend) {
                const roleField = document.getElementById('role_field');
                if (roleField) roleField.value = window.currentRole;
                return; // do not prevent default
            }

            const fd = new FormData(signupForm);
            fd.append('role', window.currentRole);

            if (window.currentRole === 'student') {
                const id = document.getElementById('student_id')?.value?.trim();
                const name = document.getElementById('student_name')?.value?.trim();
                const email = document.getElementById('student_email')?.value?.trim();
                const password = document.getElementById('student_password')?.value?.trim();
                const program = document.getElementById('student_program')?.value?.trim();
                const yearLevel = document.getElementById('student_year_level')?.value?.trim();
                const department = document.getElementById('student_department')?.value?.trim();
                const enrollmentStatus = document.getElementById('student_enrollment_status')?.value;
                const contact = document.getElementById('student_contact_number')?.value?.trim();
                const gname = document.getElementById('guardian_name')?.value?.trim();
                const gcontact = document.getElementById('guardian_contact')?.value?.trim();
                const pfile = document.getElementById('student_profile_image')?.files?.[0];

                // Validate required fields (profile image optional)
                if (!id || !name || !email || !password || !program || !yearLevel || !department || !enrollmentStatus || !contact || !gname || !gcontact) {
                    alert('Please fill in all required fields.');
                    e.preventDefault();
                    return;
                }

                fd.append('student_id', id);
                fd.append('name', name);
                fd.append('email', email);
                fd.append('password', password);
                fd.append('program', program);
                fd.append('year_level', yearLevel);
                fd.append('department', department);
                fd.append('enrollment_status', enrollmentStatus);
                fd.append('contact_number', contact);
                fd.append('guardian_name', gname);
                fd.append('guardian_contact', gcontact);
                if (pfile) fd.append('profile_image', pfile);
            } else if (window.currentRole === 'staff') {
                const name = document.getElementById('staff_name')?.value;
                const email = document.getElementById('staff_email')?.value;
                const password = document.getElementById('staff_password')?.value;
                if (!name || !email || !password) {
                    alert('Please fill in all required fields');
                    return;
                }
                fd.append('name', name);
                fd.append('email', email);
                fd.append('password', password);
            }
            // Frontend-only: no submission; log for visibility
            try { console.log('Signup form data:', Object.fromEntries(fd)); } catch {}
            e.preventDefault();
        });
    }

    // Profile dropdown toggle (dashboards)
    if (profileBtn && profileDropdown) {
        profileBtn.addEventListener('click', () => {
            const wrapper = profileBtn.closest('.profile-menu');
            if (wrapper) wrapper.classList.toggle('open');
        });
        document.addEventListener('click', (e) => {
            if (!profileBtn.closest('.profile-menu')?.contains(e.target)) {
                const wrapper = profileBtn.closest('.profile-menu');
                if (wrapper) wrapper.classList.remove('open');
            }
        });
    }

    // Notifications panel toggle
    if (notifBtn && notifPanel) {
        notifBtn.addEventListener('click', () => {
            notifPanel.classList.toggle('show');
        });
    }
    if (notifClose && notifPanel) {
        notifClose.addEventListener('click', () => notifPanel.classList.remove('show'));
    }

    // ==========================
    // Login History Modal Toggle
    // ==========================
    const loginHistoryCard = document.getElementById('loginHistoryCard');
    const loginHistoryModal = document.getElementById('loginHistoryModal');
    const loginHistClose = document.getElementById('loginHistClose');
    const loginHistCloseBtn = document.getElementById('loginHistCloseBtn');
    if (loginHistoryCard && loginHistoryModal) {
        const openLoginHistory = () => loginHistoryModal.classList.add('show');
        const closeLoginHistory = () => loginHistoryModal.classList.remove('show');

        loginHistoryCard.addEventListener('click', openLoginHistory);
        loginHistoryCard.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                openLoginHistory();
            }
        });
        if (loginHistClose) loginHistClose.addEventListener('click', closeLoginHistory);
        if (loginHistCloseBtn) loginHistCloseBtn.addEventListener('click', closeLoginHistory);
    }

    // Faculty report form: enable submit when required fields filled; show modal on submit
    const reportForm = document.getElementById('reportForm');
    if (reportForm) {
        const submitBtn = document.getElementById('submitReport');
        const requiredSelectors = ['#student_search', '#incident_dt', '#violation_type', '#location', '#description'];
        const inputs = requiredSelectors.map(s => document.querySelector(s)).filter(Boolean);
        const checkValidity = () => {
            const allFilled = inputs.every(el => el && String(el.value).trim().length > 0);
            if (submitBtn) submitBtn.disabled = !allFilled;
        };
        inputs.forEach(el => el.addEventListener('input', checkValidity));
        checkValidity();
        // In backend mode, allow native submit
        if (reportForm.dataset.mode !== 'backend') {
            const modal = document.getElementById('confirmModal');
            const modalClose = document.getElementById('modalClose');
            reportForm.addEventListener('submit', (e) => {
                e.preventDefault();
                if (modal) modal.classList.add('show');
            });
            if (modal && modalClose) {
                modalClose.addEventListener('click', () => modal.classList.remove('show'));
            }
        }
    }

    // Collapsible sections (e.g., Staff signup)
    const initCollapsibles = () => {
        document.querySelectorAll('.collapsible').forEach(section => {
            const header = section.querySelector('.collapsible-header');
            const content = section.querySelector('.collapsible-content');
            if (!header || !content) return;

            const setExpanded = (expanded) => {
                header.setAttribute('aria-expanded', expanded ? 'true' : 'false');
            };

            // Initialize height
            if (section.classList.contains('open')) {
                // Start expanded
                content.style.height = content.scrollHeight + 'px';
                // After transition time, set to auto for responsive content
                setTimeout(() => { content.style.height = 'auto'; }, 250);
                setExpanded(true);
            } else {
                content.style.height = '0px';
                setExpanded(false);
            }

            header.addEventListener('click', () => {
                const isOpen = section.classList.contains('open');
                if (isOpen) {
                    // Collapse: from current height to 0
                    const current = content.scrollHeight;
                    content.style.height = current + 'px';
                    // Force reflow
                    void content.offsetHeight;
                    content.style.height = '0px';
                    section.classList.remove('open');
                    setExpanded(false);
                } else {
                    // Expand: from 0 to scrollHeight, then set to auto
                    content.style.height = 'auto';
                    const target = content.scrollHeight;
                    content.style.height = '0px';
                    void content.offsetHeight;
                    content.style.height = target + 'px';
                    section.classList.add('open');
                    setExpanded(true);
                    const onEnd = (e) => {
                        if (e.propertyName === 'height') {
                            content.style.height = 'auto';
                            content.removeEventListener('transitionend', onEnd);
                        }
                    };
                    content.addEventListener('transitionend', onEnd);
                }
            });
        });
    };

    initCollapsibles();
});
