pkgname=grimaur-git
pkgver=r166.g2a54261
pkgrel=1
pkgdesc="Lightweight AUR helper that uses the official AUR git mirror"
arch=('any')
url="https://github.com/mackilanu/grimaur"

license=('MIT')
depends=('python' 'git')
provides=('grimaur')
conflicts=('grimaur')
source=("$pkgname::git+$url.git")
sha256sums=('SKIP')

pkgver() {
	cd "${srcdir}/${pkgname}"
	# always use git hash for version
	printf 'r%s.g%s' "$(git rev-list --count HEAD)" "$(git rev-parse --short HEAD)"
}

package() {
	cd "${srcdir}/${pkgname}"
	install -Dm755 grimaur "${pkgdir}/usr/bin/grimaur"
	sed -i "s/^__version__ = .*/__version__ = \"${pkgver}\"/" "${pkgdir}/usr/bin/grimaur"
}
