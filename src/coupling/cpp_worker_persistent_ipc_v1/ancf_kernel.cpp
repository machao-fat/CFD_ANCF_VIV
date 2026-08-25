#include "ancf_kernel.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace cfd_ancf {
namespace {
using Vec3 = std::array<double, 3>;
using Vec4 = std::array<double, 4>;
using Mat3 = std::array<double, 9>;
constexpr double EPS = 1.0e-24;
constexpr double PI = 3.141592653589793238462643383279502884;

Vec3 add(Vec3 a, const Vec3& b) { for (int i=0;i<3;++i) a[i] += b[i]; return a; }
Vec3 scale(Vec3 a, double s) { for (double& x : a) x *= s; return a; }
double dot(const Vec3& a, const Vec3& b) {
  // Match the MATLAB short-vector reduction order used by the golden
  // diagnostic.  The parenthesized tail is intentional: changing this to a
  // left-associated sum changes the bending force by several ulps.
  return a[0] * b[0] + (a[1] * b[1] + a[2] * b[2]);
}
Vec3 cross(const Vec3& a, const Vec3& b) { return {a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]}; }
Mat3 zero3() { return {0,0,0,0,0,0,0,0,0}; }
Mat3 eye3() { return {1,0,0,0,1,0,0,0,1}; }
Mat3 transpose3(const Mat3& a) { return {a[0],a[3],a[6],a[1],a[4],a[7],a[2],a[5],a[8]}; }
Mat3 add3(const Mat3& a, const Mat3& b) { Mat3 c{}; for(int i=0;i<9;++i)c[i]=a[i]+b[i]; return c; }
Mat3 scale3(const Mat3& a, double s) { Mat3 c{}; for(int i=0;i<9;++i)c[i]=a[i]*s; return c; }
Mat3 mul3(const Mat3& a, const Mat3& b) { Mat3 c=zero3(); for(int i=0;i<3;++i)for(int j=0;j<3;++j)for(int k=0;k<3;++k)c[3*i+j]+=a[3*i+k]*b[3*k+j]; return c; }
Vec3 mul3(const Mat3& a, const Vec3& b) { return {a[0]*b[0]+a[1]*b[1]+a[2]*b[2], a[3]*b[0]+a[4]*b[1]+a[5]*b[2], a[6]*b[0]+a[7]*b[1]+a[8]*b[2]}; }
Mat3 outer3(const Vec3& a, const Vec3& b) { Mat3 c{}; for(int i=0;i<3;++i)for(int j=0;j<3;++j)c[3*i+j]=a[i]*b[j]; return c; }
Mat3 cross_matrix(const Vec3& a) { return {0,-a[2],a[1],a[2],0,-a[0],-a[1],a[0],0}; }
Matrix matrix_from_mat3(const Mat3& value) {
  Matrix result(3, 3);
  for (std::size_t row = 0; row < 3; ++row)
    for (std::size_t col = 0; col < 3; ++col)
      result(row, col) = value[3 * row + col];
  return result;
}

bool finite_vector(const std::vector<double>& values) {
  return !values.empty() && std::all_of(values.begin(), values.end(),
                                        [](double value) { return std::isfinite(value); });
}

bool finite_matrix(const Matrix& value) {
  if (value.rows == 0 || value.cols == 0 ||
      value.rows > (std::numeric_limits<std::size_t>::max)() / value.cols)
    return false;
  return
         value.data.size() == value.rows * value.cols &&
         std::all_of(value.data.begin(), value.data.end(),
                     [](double item) { return std::isfinite(item); });
}

Vec4 shape(double x, double L, int derivative) {
  const double xi = x / L;
  // Match MATLAB ancf_shape.m's scalar-power contract literally.  The
  // previous multiplication expansion is algebraically equivalent but can
  // round differently at non-binary Gauss abscissae before the nonlinear
  // bending derivatives amplify the perturbation.
  const double xi2 = std::pow(xi, 2.0);
  const double xi3 = std::pow(xi, 3.0);
  const double L2 = std::pow(L, 2.0);
  if (derivative == 0) return {1-3*xi2+2*xi3, L*(xi-2*xi2+xi3), 3*xi2-2*xi3, L*(-xi2+xi3)};
  if (derivative == 1) return {(6*xi2-6*xi)/L, 1-4*xi+3*xi2, (-6*xi2+6*xi)/L, -2*xi+3*xi2};
  if (derivative == 2) return {(12*xi-6)/L2, (-4+6*xi)/L, (6-12*xi)/L2, (-2+6*xi)/L};
  throw std::invalid_argument("ANCF derivative order");
}

Matrix block_matrix(const Vec4& s) {
  Matrix out(3, 12);
  for (int block=0;block<4;++block) for (int i=0;i<3;++i) out(i,3*block+i)=s[block];
  return out;
}

std::pair<std::vector<double>, std::vector<double>> gauss(std::size_t n) {
  if (n == 3) return {{-std::sqrt(3.0/5.0),0,std::sqrt(3.0/5.0)}, {5.0/9.0,8.0/9.0,5.0/9.0}};
  if (n == 5) { const double a=std::sqrt(5+2*std::sqrt(10.0/7.0))/3; const double b=std::sqrt(5-2*std::sqrt(10.0/7.0))/3; return {{-a,-b,0,b,a},{(322-13*std::sqrt(70.0))/900,(322+13*std::sqrt(70.0))/900,128.0/225,(322+13*std::sqrt(70.0))/900,(322-13*std::sqrt(70.0))/900}}; }
  throw std::invalid_argument("ANCF gauss order");
}

void add_block(Matrix& target, std::size_t row, std::size_t col, const Matrix& block, double factor) {
  for (std::size_t i=0;i<block.rows;++i) for (std::size_t j=0;j<block.cols;++j) target(row+i,col+j) += factor*block(i,j);
}

Matrix transpose(const Matrix& a) { Matrix out(a.cols,a.rows); for(std::size_t i=0;i<a.rows;++i)for(std::size_t j=0;j<a.cols;++j)out(j,i)=a(i,j); return out; }
Matrix multiply(const Matrix& a, const Matrix& b) { Matrix out(a.rows,b.cols); for(std::size_t i=0;i<a.rows;++i)for(std::size_t k=0;k<a.cols;++k)for(std::size_t j=0;j<b.cols;++j)out(i,j)+=a(i,k)*b(k,j); return out; }
std::vector<double> multiply(const Matrix& a, const std::vector<double>& x) { if(a.cols!=x.size())throw std::invalid_argument("matrix vector dimensions"); std::vector<double> y(a.rows); for(std::size_t i=0;i<a.rows;++i)for(std::size_t j=0;j<a.cols;++j)y[i]+=a(i,j)*x[j]; return y; }
std::vector<double> solve(Matrix a, std::vector<double> b) {
  if(a.rows!=a.cols || b.size()!=a.rows)throw std::invalid_argument("linear solve dimensions");
  if (!finite_matrix(a) || !finite_vector(b))
    throw std::runtime_error("linear solve input contains NaN/Inf");
  const std::size_t n=a.rows;
#ifdef CFD_ANCF_USE_DOUBLE_SOLVE
  std::vector<double> aa = a.data, bb = std::move(b);
  for(std::size_t k=0;k<n;++k){ std::size_t pivot=k; for(std::size_t i=k+1;i<n;++i)if(std::abs(aa[i*n+k])>std::abs(aa[pivot*n+k]))pivot=i; if(std::abs(aa[pivot*n+k])<1e-24)throw std::runtime_error("singular ANCF tangent"); if(pivot!=k){for(std::size_t j=0;j<n;++j)std::swap(aa[k*n+j],aa[pivot*n+j]);std::swap(bb[k],bb[pivot]);} for(std::size_t i=k+1;i<n;++i){double f=aa[i*n+k]/aa[k*n+k];aa[i*n+k]=0;for(std::size_t j=k+1;j<n;++j)aa[i*n+j]-=f*aa[k*n+j];bb[i]-=f*bb[k];}}
  std::vector<double> xx(n); for(std::size_t ii=0;ii<n;++ii){std::size_t i=n-1-ii;double s=bb[i];for(std::size_t j=i+1;j<n;++j)s-=aa[i*n+j]*xx[j];xx[i]=s/aa[i*n+i];}
  if (!finite_vector(xx)) throw std::runtime_error("linear solve output contains NaN/Inf");
  return xx;
#else
  std::vector<long double> aa(n*n), bb(n);
  for(std::size_t i=0;i<n;++i){bb[i]=static_cast<long double>(b[i]);for(std::size_t j=0;j<n;++j)aa[i*n+j]=static_cast<long double>(a(i,j));}
  for(std::size_t k=0;k<n;++k){ std::size_t pivot=k; for(std::size_t i=k+1;i<n;++i)if(std::abs(aa[i*n+k])>std::abs(aa[pivot*n+k]))pivot=i; if(std::abs(aa[pivot*n+k])<1e-24L)throw std::runtime_error("singular ANCF tangent"); if(pivot!=k){for(std::size_t j=0;j<n;++j)std::swap(aa[k*n+j],aa[pivot*n+j]);std::swap(bb[k],bb[pivot]);} for(std::size_t i=k+1;i<n;++i){long double f=aa[i*n+k]/aa[k*n+k];aa[i*n+k]=0;for(std::size_t j=k+1;j<n;++j)aa[i*n+j]-=f*aa[k*n+j];bb[i]-=f*bb[k];}}
  std::vector<long double> xx(n); for(std::size_t ii=0;ii<n;++ii){std::size_t i=n-1-ii;long double s=bb[i];for(std::size_t j=i+1;j<n;++j)s-=aa[i*n+j]*xx[j];xx[i]=s/aa[i*n+i];}
  std::vector<double>x(n); for(std::size_t i=0;i<n;++i)x[i]=static_cast<double>(xx[i]);
  if (!finite_vector(x)) throw std::runtime_error("linear solve output contains NaN/Inf");
  return x;
#endif
}

void element_force_tangent(const std::vector<double>& qe, double Le, double EA, double EI, std::size_t ngauss, std::vector<double>& fe, Matrix& Ke) {
  fe.assign(12,0.0); Ke=Matrix(12,12);
  const auto [xi,w]=gauss(ngauss);
  for(std::size_t k=0;k<xi.size();++k){double x=0.5*(xi[k]+1)*Le; Matrix B=block_matrix(shape(x,Le,1));Matrix C=block_matrix(shape(x,Le,2));Vec3 a{},b{};for(int i=0;i<3;++i){for(int j=0;j<12;++j){a[i]+=B(i,j)*qe[j];b[i]+=C(i,j)*qe[j];}}double a2=dot(a,a);if(a2<EPS)throw std::runtime_error("degenerate ANCF tangent");Vec3 v=cross(a,b);double v2=dot(v,v);Mat3 Xa=cross_matrix(a),Xb=cross_matrix(b),Xv=cross_matrix(v);
    // Match MATLAB's literal a2^(-n) scalar-power expressions.
    const double inv_a2_3 = std::pow(a2, -3.0);
    const double inv_a2_4 = std::pow(a2, -4.0);
    const double inv_a2_5 = std::pow(a2, -5.0);
    Vec3 ga_b=add(scale(mul3(Xb,v),inv_a2_3),scale(a,-3*v2*inv_a2_4));Vec3 gb_b=scale(mul3(Xa,v),-inv_a2_3);Mat3 Haa_b=add3(add3(add3(add3(scale3(mul3(Xb,Xb),-inv_a2_3),scale3(outer3(mul3(Xb,v),a),-6*inv_a2_4)),scale3(outer3(a,mul3(Xb,v)),-3*inv_a2_4)),scale3(outer3(a,a),24*v2*inv_a2_5)),scale3(eye3(),-3*v2*inv_a2_4));Mat3 Hab=add3(scale3(add3(scale3(Xv,-1),mul3(Xb,Xa)),inv_a2_3),scale3(outer3(a,mul3(Xa,v)),3*inv_a2_4));Mat3 Hbb=scale3(mul3(Xa,Xa),-inv_a2_3);double eps=0.5*(a2-1);Vec3 ga=add(scale(a,EA*eps),scale(ga_b,EI));Vec3 gb=scale(gb_b,EI);Mat3 Haa=add3(scale3(add3(outer3(a,a),scale3(eye3(),eps)),EA),scale3(Haa_b,EI));Mat3 HabS=scale3(Hab,EI),HbbS=scale3(Hbb,EI);
    // Keep the force assembly in the same staged order as MATLAB:
    // compute B.'*ga and C.'*gb independently, add them, then apply the
    // quadrature weight.  Folding the weight and both products into one
    // accumulation changes low-magnitude components by several ulps after
    // cancellation, which is material to the strict dual-run contract.
    std::array<double, 12> bga{};
    std::array<double, 12> cgb{};
    for (int i = 0; i < 12; ++i) {
      for (int c = 0; c < 3; ++c) {
        bga[static_cast<std::size_t>(i)] += B(c, i) * ga[c];
        cgb[static_cast<std::size_t>(i)] += C(c, i) * gb[c];
      }
      // MATLAB evaluates this as term * w(k) * Le / 2; preserve the same
      // left-to-right rounding points instead of precomputing the weight.
      double term = bga[static_cast<std::size_t>(i)] +
                    cgb[static_cast<std::size_t>(i)];
      term *= w[k];
      term *= Le;
      term /= 2.0;
      fe[static_cast<std::size_t>(i)] += term;
      // MATLAB evaluates each product as an independent matrix multiplication
      // and only then adds the four 12x12 terms.  The previous scalar
      // r/s reduction interleaved all four products, changing the rounding
      // path of the effective Newton tangent by several ulps.
      const Matrix B_t = transpose(B);
      const Matrix C_t = transpose(C);
      const Matrix term_bhaa_b = multiply(multiply(B_t, matrix_from_mat3(Haa)), B);
      const Matrix term_bhab_c = multiply(multiply(B_t, matrix_from_mat3(HabS)), C);
      const Matrix term_chab_b = multiply(multiply(C_t, matrix_from_mat3(transpose3(HabS))), B);
      const Matrix term_chbb_c = multiply(multiply(C_t, matrix_from_mat3(HbbS)), C);
      for (int j = 0; j < 12; ++j) {
        double value = term_bhaa_b(i, j);
        value += term_bhab_c(i, j);
        value += term_chab_b(i, j);
        value += term_chbb_c(i, j);
        double weighted = value;
        weighted *= w[k];
        weighted *= Le;
        weighted /= 2.0;
        Ke(i, j) += weighted;
      }
    }
  }
}
}

double Model::area() const { return PI*(diameter_m*diameter_m-inner_diameter_m*inner_diameter_m)/4.0; }
double Model::displaced_area() const { return PI*diameter_m*diameter_m/4.0; }
double Model::EA() const { return youngs_modulus_Pa*area(); }
// Match the scalar multiplication path used by the MATLAB material fixture.
// The shape-function power path is handled explicitly above; retaining the
// original product order here is an independent A/B variable for the
// MATLAB/C++ forensic comparison.
double Model::EI() const {
  const double diameter_squared = diameter_m * diameter_m;
  const double inner_squared = inner_diameter_m * inner_diameter_m;
  const double diameter_fourth = diameter_squared * diameter_squared;
  const double inner_fourth = inner_squared * inner_squared;
  return youngs_modulus_Pa * PI * (diameter_fourth - inner_fourth) / 64.0;
}

void validate_model(const Model& model) {
  const auto finite = [](double value) { return std::isfinite(value); };
  if (model.elements < 1 || model.elements > 10000 || model.slices < 1 || model.slices > 1000 || model.ndof() > MAX_NDOF ||
      model.length_m <= 0.0 || model.diameter_m <= model.inner_diameter_m ||
      model.inner_diameter_m < 0.0 || model.dt_s <= 0.0 || model.beta <= 0.0 ||
      model.gamma <= 0.0 || model.max_newton == 0 || model.max_newton > MAX_NEWTON ||
      model.gauss_order != 3 && model.gauss_order != 5 ||
      model.damping_alpha != 0.0 || model.damping_beta != 0.0) {
    throw std::invalid_argument("invalid ANCF model dimensions or numerical contract");
  }
  for (double value : {model.length_m, model.diameter_m, model.inner_diameter_m,
                       model.top_tension_N, model.youngs_modulus_Pa,
                       model.material_density, model.fluid_density, model.gravity,
                       model.dt_s, model.beta, model.gamma, model.newton_tolerance,
                       model.damping_alpha, model.damping_beta}) {
    if (!finite(value)) throw std::invalid_argument("ANCF model contains NaN/Inf");
  }
  if (model.newton_tolerance <= 0.0) {
    throw std::invalid_argument("ANCF Newton tolerance must be positive");
  }
  if (!model.slice_positions_m.empty()) {
    if (model.slice_positions_m.size() != model.slices) {
      throw std::invalid_argument("ANCF slice position count mismatch");
    }
    for (std::size_t index = 0; index < model.slice_positions_m.size(); ++index) {
      const double position = model.slice_positions_m[index];
      if (!finite(position) || position < 0.0 || position > model.length_m ||
          (index > 0 && position <= model.slice_positions_m[index - 1])) {
        throw std::invalid_argument("ANCF slice positions are invalid");
      }
    }
  }
}

Matrix mapping_H3(const Model& model) {
  validate_model(model);
  Matrix H(3*model.slices,model.ndof()); const double Le=model.length_m/model.elements;
  for(std::size_t k=0;k<model.slices;++k){
    const double s = model.slice_positions_m.size()==model.slices ? model.slice_positions_m[k] :
      (model.slices==1 ? 0.0 : model.length_m*static_cast<double>(k)/(model.slices-1));
    if (s < 0.0 || s > model.length_m) throw std::invalid_argument("slice position outside case length");
    const std::size_t ie=s==model.length_m?model.elements-1:std::min(model.elements-1,static_cast<std::size_t>(std::floor(s/Le)));
    const double x=s-ie*Le;Matrix N=block_matrix(shape(x,Le,0));for(int i=0;i<3;++i)for(int j=0;j<12;++j)H(3*k+i,6*ie+j)=N(i,j);
  }return H;
}

std::vector<double> external_force(const Model& model, const std::vector<double>& slice_force) {
  validate_model(model);
  if (slice_force.size() != 3 * model.slices ||
      !std::all_of(slice_force.begin(), slice_force.end(),
                   [](double value) { return std::isfinite(value); })) {
    throw std::invalid_argument("slice force dimensions or values are invalid");
  }
  Matrix H = mapping_H3(model);
  std::vector<double> out(model.ndof());
  for (std::size_t j = 0; j < model.ndof(); ++j)
    for (std::size_t i = 0; i < 3 * model.slices; ++i)
      out[j] += H(i, j) * slice_force[i];
  if (!std::all_of(out.begin(), out.end(),
                  [](double value) { return std::isfinite(value); })) {
    throw std::runtime_error("mapped external force contains NaN/Inf");
  }
  return out;
}

void internal_force_tangent(const std::vector<double>& q, const Model& model, std::vector<double>& force, Matrix& tangent) {
  validate_model(model);
  if(q.size()!=model.ndof() || !finite_vector(q))
    throw std::invalid_argument("q dimensions or values are invalid");
  force.assign(model.ndof(),0);tangent=Matrix(model.ndof(),model.ndof());
  double Le=model.length_m/model.elements;
  for(std::size_t e=0;e<model.elements;++e){
    std::vector<double> qe(q.begin()+6*e,q.begin()+6*e+12),fe;Matrix Ke;
    element_force_tangent(qe,Le,model.EA(),model.EI(),model.gauss_order,fe,Ke);
    if (!finite_vector(fe) || !finite_matrix(Ke))
      throw std::runtime_error("ANCF internal force or tangent contains NaN/Inf");
    for(int i=0;i<12;++i){force[6*e+i]+=fe[i];for(int j=0;j<12;++j)tangent(6*e+i,6*e+j)+=Ke(i,j);}
  }
  for(std::size_t i=0;i<model.ndof();++i)for(std::size_t j=i+1;j<model.ndof();++j){double v=0.5*(tangent(i,j)+tangent(j,i));tangent(i,j)=tangent(j,i)=v;}
  if (!finite_vector(force) || !finite_matrix(tangent))
    throw std::runtime_error("ANCF assembled force or tangent contains NaN/Inf");
}

ForensicResult internal_force_forensic(const std::vector<double>& q, const Model& model) {
  validate_model(model);
  if (q.size() != model.ndof() || !finite_vector(q))
    throw std::invalid_argument("q dimensions or values are invalid");
  ForensicResult result;
  result.force.assign(model.ndof(), 0.0);
  result.tangent = Matrix(model.ndof(), model.ndof());
  const double Le = model.length_m / model.elements;
  const auto [xi, weights] = gauss(model.gauss_order);
  result.points.reserve(model.elements * xi.size());
  for (std::size_t e = 0; e < model.elements; ++e) {
    const std::vector<double> qe(q.begin() + static_cast<std::ptrdiff_t>(6 * e),
                                 q.begin() + static_cast<std::ptrdiff_t>(6 * e + 12));
    std::vector<double> element_force;
    Matrix element_tangent;
    element_force_tangent(qe, Le, model.EA(), model.EI(), model.gauss_order,
                          element_force, element_tangent);
    for (int i = 0; i < 12; ++i) {
      result.force[6 * e + static_cast<std::size_t>(i)] += element_force[static_cast<std::size_t>(i)];
      for (int j = 0; j < 12; ++j)
        result.tangent(6 * e + static_cast<std::size_t>(i),
                       6 * e + static_cast<std::size_t>(j)) += element_tangent(i, j);
    }
    for (std::size_t k = 0; k < xi.size(); ++k) {
      ForensicPoint point;
      point.element = e;
      point.gauss_index = k;
      point.xi = xi[k];
      point.x = 0.5 * (xi[k] + 1.0) * Le;
      const Matrix B = block_matrix(shape(point.x, Le, 1));
      const Matrix C = block_matrix(shape(point.x, Le, 2));
      Vec3 a{};
      Vec3 b{};
      for (int i = 0; i < 3; ++i) {
        for (int j = 0; j < 12; ++j) {
          a[static_cast<std::size_t>(i)] += B(i, j) * qe[static_cast<std::size_t>(j)];
          b[static_cast<std::size_t>(i)] += C(i, j) * qe[static_cast<std::size_t>(j)];
        }
      }
      point.a = a;
      point.b = b;
      point.a2 = dot(a, a);
      point.v = cross(a, b);
      point.v2 = dot(point.v, point.v);
      point.eps = 0.5 * (point.a2 - 1.0);
      if (point.a2 < EPS) throw std::runtime_error("degenerate ANCF tangent");
      const Mat3 Xa = cross_matrix(a);
      const Mat3 Xb = cross_matrix(b);
      const double inv_a2_3 = std::pow(point.a2, -3.0);
      const double inv_a2_4 = std::pow(point.a2, -4.0);
      point.ga_b = add(scale(mul3(Xb, point.v), inv_a2_3),
                       scale(a, -3.0 * point.v2 * inv_a2_4));
      point.gb_b = scale(mul3(Xa, point.v), -inv_a2_3);
      point.ga = add(scale(a, model.EA() * point.eps), scale(point.ga_b, model.EI()));
      point.gb = scale(point.gb_b, model.EI());
      for (int i = 0; i < 12; ++i) {
        for (int c = 0; c < 3; ++c) {
          point.bga[static_cast<std::size_t>(i)] += B(c, i) * point.ga[static_cast<std::size_t>(c)];
          point.cgb[static_cast<std::size_t>(i)] += C(c, i) * point.gb[static_cast<std::size_t>(c)];
        }
        double value = point.bga[static_cast<std::size_t>(i)] + point.cgb[static_cast<std::size_t>(i)];
        value *= weights[k];
        value *= Le;
        value /= 2.0;
        point.contribution[static_cast<std::size_t>(i)] = value;
      }
      result.points.push_back(point);
    }
  }
  for (std::size_t i = 0; i < model.ndof(); ++i)
    for (std::size_t j = i + 1; j < model.ndof(); ++j) {
      const double value = 0.5 * (result.tangent(i, j) + result.tangent(j, i));
      result.tangent(i, j) = value;
      result.tangent(j, i) = value;
    }
  return result;
}

State make_reference_state(const Model& model) {
  validate_model(model);
  State state;state.q.assign(model.ndof(),0);state.qdot.assign(model.ndof(),0);state.qddot.assign(model.ndof(),0);double Le=model.length_m/model.elements;for(std::size_t node=0;node<=model.elements;++node){std::size_t base=6*node;double s=node*Le;state.q[base+2]=s;state.q[base+5]=1.0;}state.mass=Matrix(model.ndof(),model.ndof());
  // MATLAB ancf_mass_matrix.m deliberately uses a fixed five-point rule,
  // independent of the internal-force quadrature order.  Keep the mass
  // contract separate so a valid gauss_order=3 request cannot silently
  // change inertia while the MATLAB baseline remains unchanged.
  auto [xi,w]=gauss(5);double rhoA=model.material_density*model.area();for(std::size_t e=0;e<model.elements;++e){Matrix Me(12,12);for(std::size_t k=0;k<xi.size();++k){double x=0.5*(xi[k]+1)*Le;Matrix N=block_matrix(shape(x,Le,0));Matrix Nt=transpose(N);Matrix local=multiply(Nt,N);for(std::size_t i=0;i<12;++i)for(std::size_t j=0;j<12;++j)Me(i,j)+=w[k]*local(i,j)*Le/2*rhoA;}for(int i=0;i<12;++i)for(int j=0;j<12;++j)state.mass(6*e+i,6*e+j)+=Me(i,j);}state.damping=Matrix(model.ndof(),model.ndof());state.base_load.assign(model.ndof(),0);return state;
}

void symmetrize_mass(State& state) {
  if (state.mass.rows != state.mass.cols ||
      state.mass.data.size() != state.mass.rows * state.mass.cols) {
    throw std::invalid_argument("mass matrix dimensions are invalid");
  }
  if (!std::all_of(state.mass.data.begin(), state.mass.data.end(),
                   [](double value) { return std::isfinite(value); })) {
    throw std::invalid_argument("mass matrix contains NaN/Inf");
  }
  for (std::size_t i = 0; i < state.mass.rows; ++i) {
    for (std::size_t j = i + 1; j < state.mass.cols; ++j) {
      const double value = 0.5 * (state.mass(i, j) + state.mass(j, i));
      state.mass(i, j) = value;
      state.mass(j, i) = value;
    }
  }
}

StepDiagnostics advance(State& state, const Model& model, const std::vector<double>& slice_force,
                        std::vector<NewtonIterationTrace>* trace) {
  validate_model(model);
  using Clock = std::chrono::steady_clock;
  const auto total_start = Clock::now();
  const std::size_t n = model.ndof();
  const auto valid_matrix = [n](const Matrix& value) {
    return value.rows == n && value.cols == n && value.data.size() == n * n &&
           std::all_of(value.data.begin(), value.data.end(),
                       [](double item) { return std::isfinite(item); });
  };
  const auto valid_vector = [](const std::vector<double>& values) {
    return std::all_of(values.begin(), values.end(),
                       [](double item) { return std::isfinite(item); });
  };
  if (state.q.size() != n || state.qdot.size() != n || state.qddot.size() != n ||
      state.base_load.size() != n || !valid_matrix(state.mass) || !valid_matrix(state.damping) ||
      !std::isfinite(state.time_s) || state.time_s < 0.0 ||
      !valid_vector(state.q) || !valid_vector(state.qdot) ||
      !valid_vector(state.qddot) || !valid_vector(state.base_load)) {
    throw std::invalid_argument("state dimensions or values are invalid");
  }
  if (state.step == (std::numeric_limits<std::size_t>::max)() ||
      !std::isfinite(state.time_s + model.dt_s)) {
    throw std::invalid_argument("state time or step would overflow");
  }
  std::vector<double> Qext = state.base_load;
  auto external_start = Clock::now();
  std::vector<double> qext = external_force(model, slice_force);
  const auto external_end = Clock::now();
  for (std::size_t i = 0; i < Qext.size(); ++i) Qext[i] += qext[i];
  if (!finite_vector(Qext))
    throw std::runtime_error("ANCF total external load contains NaN/Inf");
  std::vector<char> fixed(model.ndof(), 0);
  fixed[0] = fixed[1] = fixed[2] = 1;
  const std::size_t top = 6 * model.elements;
  fixed[top] = fixed[top + 1] = 1;
  // The v1 ANCF contract has prescribed bottom position [0,0,0] and a top
  // guide at x=y=0.  These values are part of the protected model contract;
  // they must not be inherited from a possibly corrupted restart state.
  const auto fixed_value = []() { return 0.0; };
  const auto predictor_start = Clock::now();
  // Keep the Newmark scalar products as named temporaries. MATLAB evaluates
  // dt^2 once for both prediction and correction; recomputing a left-associative
  // beta*dt*dt expression at the output can move qddot by several ulps.
  // MATLAB's dt^2 uses the scalar power operation. Keep the same operation
  // in the Newton predictor; a one-ulp predictor change is amplified by the
  // high-stiffness ANCF internal force.
  const double dt2 = std::pow(model.dt_s, 2.0);
  const double beta_dt2 = model.beta * dt2;
  const double gamma_dt = model.gamma * model.dt_s;
  std::vector<double> qpred = state.q, qdpred = state.qdot;
  for (std::size_t i = 0; i < model.ndof(); ++i) {
    // Force the same two rounded vector additions MATLAB performs.  Keeping
    // the intermediates volatile prevents MSVC from contracting the three
    // terms into an FMA under optimized builds.
    volatile double position = qpred[i];
    volatile double velocity_term = model.dt_s * state.qdot[i];
    volatile double acceleration_term = dt2 * (0.5 - model.beta) * state.qddot[i];
    position += velocity_term;
    position += acceleration_term;
    qpred[i] = position;
    volatile double velocity = qdpred[i];
    volatile double acceleration_velocity = model.dt_s * (1 - model.gamma) * state.qddot[i];
    velocity += acceleration_velocity;
    qdpred[i] = velocity;
  }
  const auto predictor_end = Clock::now();
  std::vector<double> q = qpred;
  for (std::size_t i = 0; i < model.ndof(); ++i) if (fixed[i]) q[i] = fixed_value();
  StepDiagnostics d;
  // MATLAB evaluates max(1,norm(Qext(free),inf)); prescribed-DOF reactions
  // must not loosen the convergence threshold for free coordinates.
  double scale_value = 1.0;
  for (std::size_t i = 0; i < Qext.size(); ++i)
    if (!fixed[i]) scale_value = std::max(scale_value, std::abs(Qext[i]));
  d.residual_scale = scale_value;
  for (std::size_t iter = 1; iter <= model.max_newton; ++iter) {
    std::vector<double> qdd(model.ndof()), qd(model.ndof());
    for (std::size_t i = 0; i < model.ndof(); ++i) {
      qdd[i] = (q[i] - qpred[i]) / beta_dt2;
      qd[i] = qdpred[i] + gamma_dt * qdd[i];
    }
    std::vector<double> qi;
    Matrix K;
    const auto assembly_start = Clock::now();
    internal_force_tangent(q, model, qi, K);
    if (!finite_vector(qi) || !finite_matrix(K))
      throw std::runtime_error("ANCF Newton assembly contains NaN/Inf");
    const auto assembly_end = Clock::now();
    d.matrix_assembly_s += std::chrono::duration<double>(assembly_end - assembly_start).count();
    // Keep the residual stages separate, matching MATLAB's
    // M*qdd + C*qd + Qint - Qext expression.  Combining the two matrix-vector
    // products and subtracting Qext inside the same accumulation changes
    // cancellation order and can perturb a later Newton increment.
    std::vector<double> inertia(model.ndof());
    std::vector<double> damping_force(model.ndof());
    for (std::size_t i = 0; i < model.ndof(); ++i) {
      for (std::size_t j = 0; j < model.ndof(); ++j) {
        inertia[i] += state.mass(i, j) * qdd[j];
        damping_force[i] += state.damping(i, j) * qd[j];
      }
    }
    std::vector<double> R(model.ndof());
    for (std::size_t i = 0; i < model.ndof(); ++i) {
      R[i] = inertia[i] + damping_force[i];
      R[i] += qi[i];
      R[i] -= Qext[i];
      if (fixed[i]) R[i] = 0.0;
    }
    if (!finite_vector(R)) throw std::runtime_error("ANCF residual contains NaN/Inf");
    double norm = 0.0;
    for (std::size_t i = 0; i < R.size(); ++i) if (!fixed[i]) norm = std::max(norm, std::abs(R[i]));
    if (iter == 1) d.initial_residual = norm;
    d.residual = norm;
    d.iterations = iter;
    NewtonIterationTrace iteration_trace;
    if (trace != nullptr) {
      iteration_trace.iteration = iter;
      iteration_trace.q = q;
      iteration_trace.qdot = qd;
      iteration_trace.qddot = qdd;
      iteration_trace.internal_force = qi;
      iteration_trace.residual = R;
      iteration_trace.tangent = K;
      iteration_trace.residual_norm = norm;
    }
    if (norm <= model.newton_tolerance * scale_value) {
      d.converged = true;
      if (trace != nullptr) {
        iteration_trace.converged = true;
        trace->push_back(std::move(iteration_trace));
      }
      state.qddot = qdd;
      state.qdot = qd;
      break;
    }
    // Preserve MATLAB's expression and addition order exactly:
    // M/(beta*dt^2) + C*gamma/(beta*dt) + Kint.  Starting from Kint and
    // adding the inertial terms changes the last bits of Keff, which changes
    // the Newton increment and is amplified by the high-stiffness internal
    // force in the strict MATLAB/C++ dual run.
    Matrix Keff(model.ndof(), model.ndof());
    const double inv_beta_dt2 = 1.0 / beta_dt2;
    const double inv_beta_dt = 1.0 / (model.beta * model.dt_s);
    for (std::size_t i = 0; i < model.ndof(); ++i)
      for (std::size_t j = 0; j < model.ndof(); ++j) {
        const double mass_term = state.mass(i, j) * inv_beta_dt2;
        const double damping_term = state.damping(i, j) * model.gamma * inv_beta_dt;
        Keff(i, j) = mass_term + damping_term;
        Keff(i, j) += K(i, j);
      }
    if (!finite_matrix(Keff)) throw std::runtime_error("ANCF effective tangent contains NaN/Inf");
    std::vector<std::size_t> free;
    for (std::size_t i = 0; i < model.ndof(); ++i) if (!fixed[i]) free.push_back(i);
    Matrix Kff(free.size(), free.size());
    std::vector<double> Rf(free.size());
    for (std::size_t i = 0; i < free.size(); ++i) {
      Rf[i] = R[free[i]];
      for (std::size_t j = 0; j < free.size(); ++j) Kff(i, j) = Keff(free[i], free[j]);
    }
    const auto solve_start = Clock::now();
    auto dq = solve(Kff, Rf);
    if (!finite_vector(dq)) throw std::runtime_error("ANCF Newton increment contains NaN/Inf");
    if (trace != nullptr) {
      iteration_trace.increment.assign(model.ndof(), 0.0);
      for (std::size_t i = 0; i < free.size(); ++i)
        iteration_trace.increment[free[i]] = -dq[i];
      trace->push_back(std::move(iteration_trace));
    }
    const auto solve_end = Clock::now();
    d.linear_solve_s += std::chrono::duration<double>(solve_end - solve_start).count();
    for (std::size_t i = 0; i < free.size(); ++i) q[free[i]] -= dq[i];
    for (std::size_t i = 0; i < model.ndof(); ++i) if (fixed[i]) q[i] = fixed_value();
  }
  if (!d.converged) throw std::runtime_error("ANCF Newton did not converge");
  // MATLAB recomputes the accepted acceleration and velocity after Newton
  // exits. Do the same from the final q, rather than retaining the values
  // calculated before the convergence check.
  std::vector<double> final_qdd(model.ndof()), final_qd(model.ndof());
  for (std::size_t i = 0; i < model.ndof(); ++i) {
    final_qdd[i] = (q[i] - qpred[i]) / beta_dt2;
    final_qd[i] = qdpred[i] + gamma_dt * final_qdd[i];
  }
  const auto update_start = Clock::now();
  state.q = q;
  state.qddot = std::move(final_qdd);
  state.qdot = std::move(final_qd);
  state.time_s += model.dt_s;
  ++state.step;
  state.residual = d.residual;
  state.iterations = d.iterations;
  const auto update_end = Clock::now();
  d.state_update_s = std::chrono::duration<double>(update_end - update_start).count();
  d.predictor_s = std::chrono::duration<double>(predictor_end - predictor_start).count();
  d.external_mapping_s = std::chrono::duration<double>(external_end - external_start).count();
  (void)total_start;
  return d;
}

bool finite(const State& state) {
  const auto ok = [](const std::vector<double>& values) {
    return std::all_of(values.begin(), values.end(),
                       [](double value) { return std::isfinite(value); });
  };
  const auto matrix_ok = [](const Matrix& value) {
    return value.rows == value.cols && value.data.size() == value.rows * value.cols &&
           std::all_of(value.data.begin(), value.data.end(),
                       [](double item) { return std::isfinite(item); });
  };
  return ok(state.q) && ok(state.qdot) && ok(state.qddot) && ok(state.base_load) &&
         matrix_ok(state.mass) && matrix_ok(state.damping) && std::isfinite(state.time_s) &&
         std::isfinite(state.residual);
}

}  // namespace cfd_ancf
