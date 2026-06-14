pkgname=grimoire-git
pkgver=r216.g17893eb
pkgrel=1
pkgdesc="Lightweight AUR helper that uses the official AUR git mirror"
arch=('any')
url="https://github.com/mackilanu/grimoire"
_dev_url="https://github.com/h8d13/grimaur3"
_dev_branch="dot-cache"

license=('MIT')
depends=('python' 'git')
provides=('grimoire')
conflicts=('grimoire')
source=("$pkgname::git+$_dev_url.git#branch=$_dev_branch")
sha256sums=('SKIP')

pkgver() {
	cd "${srcdir}/${pkgname}"
	# always use git hash for version
	printf 'r%s.g%s' "$(git rev-list --count HEAD)" "$(git rev-parse --short HEAD)"
}

package() {
	cd "${srcdir}/${pkgname}"
	install -Dm755 grimoire "${pkgdir}/usr/bin/grimoire"
	sed -i "s/^__version__ = .*/__version__ = \"${pkgver}\"/" "${pkgdir}/usr/bin/grimoire"
}
