<script lang="ts">
	import DOMPurify from 'dompurify';
	import { marked } from 'marked';

	import { toast } from 'svelte-sonner';

	import { onMount, getContext, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	import { getBackendConfig } from '$lib/apis';
	import { ldapUserSignIn, getSessionUser, userSignIn, userSignUp } from '$lib/apis/auths';

	import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';
	import { WEBUI_NAME, config, user, socket } from '$lib/stores';

	import { generateInitialsImage, canvasPixelTest } from '$lib/utils';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import OnBoarding from '$lib/components/OnBoarding.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import { redirect } from '@sveltejs/kit';

	const i18n = getContext('i18n');

	let loaded = false;

	let mode = $config?.features.enable_ldap ? 'ldap' : 'signin';

	let form = null;

	let name = '';
	let email = '';
	let password = '';
	let confirmPassword = '';

	let ldapUsername = '';

	const setSessionUser = async (sessionUser, redirectPath: string | null = null) => {
		if (sessionUser) {
			console.log(sessionUser);
			toast.success($i18n.t(`You're now logged in.`));
			if (sessionUser.token) {
				localStorage.token = sessionUser.token;
			}
			$socket.emit('user-join', { auth: { token: sessionUser.token } });
			await user.set(sessionUser);
			await config.set(await getBackendConfig());

			if (!redirectPath) {
				redirectPath = $page.url.searchParams.get('redirect') || '/';
			}

			goto(redirectPath);
			localStorage.removeItem('redirectPath');
		}
	};

	const signInHandler = async () => {
		const sessionUser = await userSignIn(email, password).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		await setSessionUser(sessionUser);
	};

	const signUpHandler = async () => {
		if ($config?.features?.enable_signup_password_confirmation) {
			if (password !== confirmPassword) {
				toast.error($i18n.t('Passwords do not match.'));
				return;
			}
		}

		const sessionUser = await userSignUp(name, email, password, generateInitialsImage(name)).catch(
			(error) => {
				toast.error(`${error}`);
				return null;
			}
		);

		await setSessionUser(sessionUser);
	};

	const ldapSignInHandler = async () => {
		const sessionUser = await ldapUserSignIn(ldapUsername, password).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		await setSessionUser(sessionUser);
	};

	const submitHandler = async () => {
		if (mode === 'ldap') {
			await ldapSignInHandler();
		} else if (mode === 'signin') {
			await signInHandler();
		} else {
			await signUpHandler();
		}
	};

	const oauthCallbackHandler = async () => {
		// Get the value of the 'token' cookie
		function getCookie(name) {
			const match = document.cookie.match(
				new RegExp('(?:^|; )' + name.replace(/([.$?*|{}()[\]\\/+^])/g, '\\$1') + '=([^;]*)')
			);
			return match ? decodeURIComponent(match[1]) : null;
		}

		const token = getCookie('token');
		if (!token) {
			return;
		}

		const sessionUser = await getSessionUser(token).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (!sessionUser) {
			return;
		}

		localStorage.token = token;
		await setSessionUser(sessionUser, localStorage.getItem('redirectPath') || null);
	};

	let onboarding = false;

	async function setLogoImage() {
		await tick();
		const logo = document.getElementById('logo');

		if (logo) {
			const isDarkMode = document.documentElement.classList.contains('dark');

			if (isDarkMode) {
				const darkImage = new Image();
				darkImage.src = `${WEBUI_BASE_URL}/static/favicon-dark.png`;

				darkImage.onload = () => {
					logo.src = `${WEBUI_BASE_URL}/static/favicon-dark.png`;
					logo.style.filter = ''; // Ensure no inversion is applied if favicon-dark.png exists
				};

				darkImage.onerror = () => {
					logo.style.filter = 'invert(1)'; // Invert image if favicon-dark.png is missing
				};
			}
		}
	}

	onMount(async () => {
		const redirectPath = $page.url.searchParams.get('redirect');
		if ($user !== undefined) {
			goto(redirectPath || '/');
		} else {
			if (redirectPath) {
				localStorage.setItem('redirectPath', redirectPath);
			}
		}

		const error = $page.url.searchParams.get('error');
		if (error) {
			toast.error(error);
		}

		await oauthCallbackHandler();
		form = $page.url.searchParams.get('form');

		loaded = true;
		setLogoImage();

		if (($config?.features.auth_trusted_header ?? false) || $config?.features.auth === false) {
			await signInHandler();
		} else {
			onboarding = $config?.onboarding ?? false;
		}
	});
</script>

<svelte:head>
	<title>
		{`${$WEBUI_NAME}`}
	</title>
</svelte:head>

<OnBoarding
	bind:show={onboarding}
	getStartedHandler={() => {
		onboarding = false;
		mode = $config?.features.enable_ldap ? 'ldap' : 'signup';
	}}
/>

<div
	class="w-full h-screen max-h-[100dvh] text-white relative"
	style="direction: rtl;"
	id="auth-page"
>
	<div class="w-full h-full absolute top-0 left-0 bg-white dark:bg-black"></div>

	<div class="w-full absolute top-0 left-0 right-0 h-8 drag-region" />

	{#if loaded}
		<div
			class="relative bg-transparent h-screen overflow-y-scroll font-primary z-50 text-black dark:text-white pb-24"
			id="auth-container"
		>
			<div class="w-full px-2 min-h-screen flex flex-col text-center">
				<div class="my-auto flex flex-col justify-center items-center">
					<div class=" sm:max-w-md my-auto pb-10 w-full dark:text-gray-100">
						<div class="flex justify-center">
							<img
								id="logo"
								crossorigin="anonymous"
								src="{WEBUI_BASE_URL}/static/logotext.png"
								class="size-24 rounded-full"
								alt=""
							/>
						</div>

						<div class="mb-1">
							<div class="max-w-md">
								<h1 class="text-2xl font-bold mb-1 leading-relaxed">
									جعوک راهنمایی برای کشف، نه فقط یک مسیر
								</h1>
								<p class="text-sm leading-7 mb-1">
									جعوک یک هوش مصنوعی برای سفرهای پرماجرا است. در گام نخست، جعوک با تمرکز بر قشم و
									جزایر اطراف، به گردشگران و ساکنان کمک می‌کند تا در کوتاه‌ترین زمان، به دقیق‌ترین و
									کاربردی‌ترین اطلاعات دسترسی داشته باشند.
								</p>

								<p class="text-sm leading-7 mb-1">
									جعوک، راهنمای بومی هوشمند شما در سفر به قشم است. از جاذبه‌های طبیعی و تاریخی گرفته
									تا فرهنگ و آداب محلی، اقامتگاه‌ها، رستوران‌ها، کافه‌ها و مراکز خرید و… هر آنچه
									باید پیش از سفر بدانید در جعوک گردآوری شده است. با جعوک، سفر به قشم و جزایر اطراف
									تجربه‌ای آسان‌تر، آگاهانه‌تر و لذت‌بخش‌تر خواهد بود.
								</p>

								<p class="text-sm leading-7 mb-1">
									جعوک تنها برای گردشگران نیست. می‌توانید با جعوک به‌سرعت تعمیرکاران تخصصی، خدمات
									درمانی، فروشگاه‌ها، مراکز اداری و سایر خدمات شهری را پیدا کنید.
								</p>

								<p class="text-sm leading-7 mb-1">
									کسب‌وکارهای محلی نیز می‌توانند با حضور در جعوک، بهتر دیده شوند و مشتریان بیشتری
									جذب کنند. تمامی این امکانات به‌صورت کاملاً رایگان در اختیار کاربران و صاحبان
									کسب‌وکار قرار دارد.
								</p>
							</div>
						</div>

						{#if Object.keys($config?.oauth?.providers ?? {}).length > 0}
							<div class="inline-flex items-center justify-center w-full">
								<hr class="w-32 h-px my-4 border-0 dark:bg-gray-100/10 bg-gray-700/10" />
								{#if $config?.features.enable_login_form || $config?.features.enable_ldap || form}
									<span
										class="px-3 text-sm font-medium text-gray-900 dark:text-white bg-transparent"
										>{$i18n.t('or')}</span
									>
								{/if}

								<hr class="w-32 h-px my-4 border-0 dark:bg-gray-100/10 bg-gray-700/10" />
							</div>
							<div class="fixed bottom-0 left-0 w-full z-50">
								{#if $config?.oauth?.providers?.google}
									<button
										class="flex justify-center items-center w-full
		bg-gray-200 hover:bg-gray-300
		dark:bg-gray-850 dark:hover:bg-gray-700
		dark:text-gray-300 dark:hover:text-white
		transition font-medium text-sm py-4
		border-t border-gray-300/40 dark:border-gray-700/60"
										on:click={() => {
											window.location.href = `${WEBUI_BASE_URL}/oauth/google/login`;
										}}
									>
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" class="size-6 ml-3">
											<path
												fill="#EA4335"
												d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
											/>
											<path
												fill="#4285F4"
												d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
											/>
											<path
												fill="#FBBC05"
												d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
											/>
											<path
												fill="#34A853"
												d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
											/>
											<path fill="none" d="M0 0h48v48H0z" />
										</svg>
										<span>{$i18n.t('Continue with {{provider}}', { provider: 'گوگل' })}</span>
									</button>
								{/if}
							</div>
						{/if}
					</div>
				</div>
			</div>
		</div>

		{#if !$config?.metadata?.auth_logo_position}
			<div class="fixed m-10 z-50">
				<div class="flex space-x-2">
					<div class=" self-center">
						<img
							id="logo"
							crossorigin="anonymous"
							src="{WEBUI_BASE_URL}/static/favicon.png"
							class=" w-6 rounded-full"
							alt=""
						/>
					</div>
				</div>
			</div>
		{/if}
	{/if}
</div>
